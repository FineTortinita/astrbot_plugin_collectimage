import asyncio
import hashlib
import io
import os
import secrets
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from aiohttp import web
from PIL import Image

from astrbot.api import logger


# 缩略图默认配置（可被配置覆盖）
DEFAULT_THUMBNAIL_SIZE = 300
DEFAULT_THUMBNAIL_CACHE_SIZE = 500
THUMBNAIL_CACHE_DIR = None


def _get_thumbnail_cache_dir() -> Path:
    """获取缩略图缓存目录"""
    global THUMBNAIL_CACHE_DIR
    if THUMBNAIL_CACHE_DIR is None:
        THUMBNAIL_CACHE_DIR = Path(__file__).parent / "web" / "cache" / "thumbs"
        THUMBNAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return THUMBNAIL_CACHE_DIR


def _generate_thumbnail_cached(image_path: str, thumbnail_size: int = DEFAULT_THUMBNAIL_SIZE) -> bytes:
    """生成缩略图（带缓存）"""
    try:
        with Image.open(image_path) as img:
            img.thumbnail((thumbnail_size, thumbnail_size), Image.Resampling.LANCZOS)
            
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=85, optimize=True)
            return buffer.getvalue()
    except Exception as e:
        logger.error(f"[CollectImage] 生成缩略图失败: {image_path}, {e}")
        return b""


class WebServer:
    CLIENT_MAX_SIZE = 50 * 1024 * 1024
    SESSION_TIMEOUT = 3600

    def __init__(self, plugin: Any, host: str = "0.0.0.0", port: int = 9192):
        self.plugin = plugin
        self.host = host
        self.port = port
        self.app = web.Application(
            client_max_size=self.CLIENT_MAX_SIZE,
            middlewares=[self._cors_middleware, self._error_middleware, self._auth_middleware],
        )
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self._started = False

        self.static_dir = Path(__file__).parent / "web"
        self.images_dir = str(self.plugin.images_dir)
        logger.info(f"[CollectImage] WebUI 图片目录: {self.images_dir}")

        self._cookie_name = "collectimage_webui_session"
        self._sessions: dict[str, float] = {}
        
        # 登录限制
        self._login_attempts: dict[str, list[float]] = {}  # IP -> [timestamp1, timestamp2, ...]
        self._blocked_ips: dict[str, float] = {}  # IP -> unblock_timestamp
        self.MAX_LOGIN_ATTEMPTS = 3
        self.BLOCK_DURATION = 300  # 5分钟封禁
        self.ATTEMPT_WINDOW = 300  # 5分钟内
        
        self._import_state = {
            "running": False,
            "total": 0,
            "imported": 0,
            "stop_requested": False
        }

        self._setup_routes()

    def _setup_routes(self):
        self.app.router.add_post("/api/auth/login", self.handle_login)
        self.app.router.add_get("/api/auth/info", self.handle_auth_info)
        self.app.router.add_post("/api/auth/logout", self.handle_logout)

        self.app.router.add_get("/api/images", self.handle_list_images)
        self.app.router.add_get("/api/images/search", self.handle_search_images)
        self.app.router.add_get("/api/images/{image_id}", self.handle_get_image)
        self.app.router.add_put("/api/images/{image_id}", self.handle_update_image)
        self.app.router.add_delete("/api/images/{image_id}", self.handle_delete_image)
        self.app.router.add_post("/api/images/{image_id}/reanalyze", self.handle_reanalyze)
        self.app.router.add_post("/api/images/{image_id}/recognize_character", self.handle_recognize_character)
        self.app.router.add_put("/api/images/{image_id}/confirm", self.handle_confirm_image)

        self.app.router.add_get("/api/aliases", self.handle_list_aliases)
        self.app.router.add_post("/api/aliases", self.handle_add_alias)
        self.app.router.add_delete("/api/aliases/{alias_id}", self.handle_delete_alias)
        self.app.router.add_post("/api/aliases/import", self.handle_import_aliases)
        self.app.router.add_get("/api/aliases/import/status", self.handle_import_status)
        self.app.router.add_post("/api/aliases/import/stop", self.handle_import_stop)

        self.app.router.add_post("/api/maintenance/cleanup", self.handle_cleanup)
        self.app.router.add_get("/api/stats", self.handle_get_stats)
        self.app.router.add_get("/api/health", self.handle_health_check)

        # 配置管理
        self.app.router.add_get("/api/config", self.handle_get_config)
        self.app.router.add_put("/api/config", self.handle_update_config)
        self.app.router.add_get("/api/config/schema", self.handle_get_config_schema)

        # 文件上传
        self.app.router.add_post("/api/images/upload", self.handle_upload_image)

        # 批量操作
        self.app.router.add_delete("/api/images/batch", self.handle_batch_delete_images)
        self.app.router.add_put("/api/images/batch/confirm", self.handle_batch_confirm_images)

        self.app.router.add_get("/", self.handle_index)
        self.app.router.add_get("/index.html", self.handle_index)
        self.app.router.add_get("/favicon.ico", self.handle_favicon)
        self.app.router.add_get("/web/{path:.*}", self.handle_web_static)
        self.app.router.add_get("/images/{path:.*}", self.handle_images_static)

    @staticmethod
    def _ok(data: dict = None, **kwargs) -> web.Response:
        body = {"success": True}
        if data:
            body.update(data)
        if kwargs:
            body.update(kwargs)
        return web.json_response(body)

    @staticmethod
    def _err(msg: str, status: int = 500) -> web.Response:
        return web.json_response({"success": False, "error": msg}, status=status)

    async def _check_auth(self, request: web.Request) -> bool:
        session = request.cookies.get(self._cookie_name)
        if not session:
            return False
        expire_time = self._sessions.get(session, 0)
        if expire_time < time.time():
            if session in self._sessions:
                del self._sessions[session]
            return False
        return True

    def _get_client_ip(self, request: web.Request) -> str:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        return request.remote or "unknown"

    def _is_ip_blocked(self, ip: str) -> bool:
        if ip not in self._blocked_ips:
            return False
        if time.time() > self._blocked_ips[ip]:
            del self._blocked_ips[ip]
            if ip in self._login_attempts:
                del self._login_attempts[ip]
            return False
        return True

    def _record_failed_attempt(self, ip: str):
        now = time.time()
        if ip not in self._login_attempts:
            self._login_attempts[ip] = []
        self._login_attempts[ip].append(now)
        cutoff = now - self.ATTEMPT_WINDOW
        self._login_attempts[ip] = [t for t in self._login_attempts[ip] if t > cutoff]
        if len(self._login_attempts[ip]) >= self.MAX_LOGIN_ATTEMPTS:
            self._blocked_ips[ip] = now + self.BLOCK_DURATION
            logger.warning(f"[CollectImage] IP {ip} 已被封禁 {self.BLOCK_DURATION} 秒")

    def _get_block_remaining(self, ip: str) -> int:
        if ip not in self._blocked_ips:
            return 0
        remaining = int(self._blocked_ips[ip] - time.time())
        return max(0, remaining)

    @web.middleware
    async def _cors_middleware(self, request: web.Request, handler):
        response = await handler(request)
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response

    @web.middleware
    async def _auth_middleware(self, request: web.Request, handler):
        if request.path.startswith("/api/auth/"):
            return await handler(request)
        if request.path.startswith("/web/") or request.path.startswith("/images/") or request.path == "/" or request.path == "/index.html" or request.path == "/favicon.ico":
            return await handler(request)
        if not await self._check_auth(request):
            return web.json_response({"success": False, "error": "未登录", "code": 401}, status=401)
        return await handler(request)

    @web.middleware
    async def _error_middleware(self, request: web.Request, handler):
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except Exception as e:
            logger.error(f"[CollectImage WebUI] 请求错误: {e}")
            return self._err(str(e))

    async def handle_login(self, request: web.Request) -> web.Response:
        try:
            client_ip = self._get_client_ip(request)
            
            if self._is_ip_blocked(client_ip):
                remaining = self._get_block_remaining(client_ip)
                minutes = remaining // 60
                seconds = remaining % 60
                return self._err(f"登录过于频繁，请等待 {minutes}分{seconds}秒 后重试", 429)
            
            data = await request.json()
            password = data.get("password", "")
            expected_password = getattr(self.plugin.config, "webui_password", "") or "admin123"
            
            if password == expected_password:
                if client_ip in self._login_attempts:
                    del self._login_attempts[client_ip]
                
                session = secrets.token_hex(16)
                self._sessions[session] = time.time() + self.SESSION_TIMEOUT
                response = self._ok({"message": "登录成功"})
                response.set_cookie(
                    self._cookie_name, 
                    session, 
                    path="/",
                    httponly=True, 
                    max_age=self.SESSION_TIMEOUT,
                    samesite="Lax"
                )
                return response
            
            self._record_failed_attempt(client_ip)
            attempts = len(self._login_attempts.get(client_ip, []))
            return self._err(f"密码错误（{attempts}/{self.MAX_LOGIN_ATTEMPTS}）", 401)
        except Exception as e:
            return self._err(f"登录失败: {e}")

    async def handle_auth_info(self, request: web.Request) -> web.Response:
        is_logged_in = await self._check_auth(request)
        return self._ok({"logged_in": is_logged_in})

    async def handle_logout(self, request: web.Request) -> web.Response:
        session = request.cookies.get(self._cookie_name)
        if session and session in self._sessions:
            del self._sessions[session]
        response = self._ok({"message": "已退出登录"})
        response.del_cookie(self._cookie_name, path="/")
        return response

    async def handle_list_images(self, request: web.Request) -> web.Response:
        tag = request.query.get("tag")
        character = request.query.get("character")
        description = request.query.get("description")
        group_id = request.query.get("group_id")
        confirmed = request.query.get("confirmed")
        max_limit = getattr(self.plugin.config, 'max_api_images', 50)
        limit = int(request.query.get("limit", max_limit))
        offset = int(request.query.get("offset", 0))
        
        # 限制最大数量
        if limit > max_limit:
            limit = max_limit
        
        confirmed_val = None
        if confirmed is not None:
            confirmed_val = int(confirmed)

        images = self.plugin.db.search_images(
            tag=tag,
            character=character,
            description=description,
            group_id=group_id,
            confirmed=confirmed_val,
            limit=limit,
            offset=offset,
            random=True,
        )
        total = self.plugin.db.count_images(confirmed=confirmed_val)
        
        for img in images:
            if img.get("tags"):
                try:
                    img["tags"] = json.loads(img["tags"])
                except:
                    pass
        return self._ok({"images": images, "total": total})

    async def handle_search_images(self, request: web.Request) -> web.Response:
        """搜索图片（支持别名匹配，与 /moe 命令相同的搜索逻辑）"""
        keyword = request.query.get("keyword", "")
        max_limit = getattr(self.plugin.config, 'max_api_images', 50)
        limit = int(request.query.get("limit", max_limit))
        confirmed = request.query.get("confirmed")
        
        if not keyword:
            return self._err("关键词不能为空")
        
        # 限制最大数量
        if limit > max_limit:
            limit = max_limit
        
        confirmed_val = None
        if confirmed is not None:
            confirmed_val = int(confirmed)
        
        # 优先搜索角色（含别名匹配）
        images = self.plugin.db.search_character_random_with_alias(keyword=keyword, limit=limit)
        
        # 角色没找到再搜索标签和描述（含别名匹配）
        if not images:
            images = self.plugin.db.search_all_random_with_alias(keyword=keyword, limit=limit)
        
        # 如果有确认状态筛选，在结果中过滤
        if confirmed_val is not None:
            images = [img for img in images if img.get("confirmed") == confirmed_val]
        
        for img in images:
            if img.get("tags"):
                try:
                    img["tags"] = json.loads(img["tags"])
                except:
                    pass
        
        return self._ok({"images": images, "total": len(images), "keyword": keyword})

    async def handle_get_image(self, request: web.Request) -> web.Response:
        image_id = int(request.match_info["image_id"])
        image = self.plugin.db.get_image_by_id(image_id)
        if not image:
            return self._err("图片不存在", 404)
        if image.get("tags"):
            try:
                image["tags"] = json.loads(image["tags"])
            except:
                pass
        return self._ok({"image": image})

    async def handle_update_image(self, request: web.Request) -> web.Response:
        image_id = int(request.match_info["image_id"])
        data = await request.json()
        tags = data.get("tags")
        character = data.get("character")
        description = data.get("description")
        
        success = self.plugin.db.update_image(
            image_id=image_id,
            tags=tags,
            character=character,
            description=description,
        )
        if success:
            return self._ok({"message": "更新成功"})
        return self._err("更新失败")

    async def handle_delete_image(self, request: web.Request) -> web.Response:
        image_id = int(request.match_info["image_id"])
        image = self.plugin.db.get_image_by_id(image_id)
        if not image:
            return self._err("图片不存在", 404)
        
        try:
            if os.path.exists(image["file_path"]):
                os.remove(image["file_path"])
        except Exception as e:
            logger.warning(f"[CollectImage] 删除图片文件失败: {e}")
        
        self.plugin.db.delete_image(image_id)
        return self._ok({"message": "删除成功"})

    async def handle_batch_delete_images(self, request: web.Request) -> web.Response:
        """批量删除图片"""
        try:
            data = await request.json()
            image_ids = data.get("image_ids", [])
            
            if not image_ids:
                return self._err("请选择要删除的图片")
            
            if len(image_ids) > 100:
                return self._err("单次最多删除100张图片")
            
            deleted_count = 0
            for image_id in image_ids:
                image = self.plugin.db.get_image_by_id(image_id)
                if image:
                    try:
                        if os.path.exists(image["file_path"]):
                            os.remove(image["file_path"])
                    except Exception as e:
                        logger.warning(f"[CollectImage] 删除图片文件失败: {e}")
                    self.plugin.db.delete_image(image_id)
                    deleted_count += 1
            
            return self._ok({"message": f"成功删除 {deleted_count} 张图片", "deleted": deleted_count})
        except Exception as e:
            logger.error(f"[CollectImage] 批量删除失败: {e}")
            return self._err(str(e))

    async def handle_batch_confirm_images(self, request: web.Request) -> web.Response:
        """批量确认/取消确认图片"""
        try:
            data = await request.json()
            image_ids = data.get("image_ids", [])
            confirmed = data.get("confirmed", True)
            
            if not image_ids:
                return self._err("请选择要操作的图片")
            
            if len(image_ids) > 100:
                return self._err("单次最多操作100张图片")
            
            confirmed_val = 1 if confirmed else 0
            updated_count = 0
            for image_id in image_ids:
                image = self.plugin.db.get_image_by_id(image_id)
                if image:
                    self.plugin.db.update_confirmed(image_id, confirmed_val)
                    updated_count += 1
            
            action = "确认" if confirmed else "取消确认"
            return self._ok({"message": f"成功{action} {updated_count} 张图片", "updated": updated_count})
        except Exception as e:
            logger.error(f"[CollectImage] 批量操作失败: {e}")
            return self._err(str(e))

    async def handle_reanalyze(self, request: web.Request) -> web.Response:
        image_id = int(request.match_info["image_id"])
        image = self.plugin.db.get_image_by_id(image_id)
        if not image:
            return self._err("图片不存在", 404)
        
        image_url = image.get("file_path")
        if not image_url:
            return self._err("图片路径不存在", 404)
        
        try:
            result = await self.plugin.reanalyze_image(image_url)
            self.plugin.db.update_image(
                image_id=image_id,
                tags=result.get("tags"),
                character=result.get("character"),
                description=result.get("description"),
            )
            return self._ok({"result": result})
        except Exception as e:
            return self._err(f"重新分析失败: {e}")

    async def handle_recognize_character(self, request: web.Request) -> web.Response:
        image_id = int(request.match_info["image_id"])
        image = self.plugin.db.get_image_by_id(image_id)
        if not image:
            return self._err("图片不存在", 404)
        
        image_path = image.get("file_path")
        if not image_path:
            return self._err("图片路径不存在", 404)
        
        try:
            # 使用本地文件 base64 方式识别
            result = await self.plugin.recognize_character_from_file(image_path)
            
            # 从 AnimeTrace 结果直接提取角色（根据结果数量确定人数）
            character = self.plugin._extract_characters(result.get("all_results", []))
            
            # 更新数据库
            self.plugin.db.update_character(image_id, character)
            
            return self._ok({"result": result, "character": character})
        except Exception as e:
            logger.error(f"[CollectImage WebUI] 角色识别失败: {e}")
            return self._err(f"角色识别失败: {e}")

    async def handle_confirm_image(self, request: web.Request) -> web.Response:
        """更新图片确认状态"""
        if not await self._check_auth(request):
            return self._err("Unauthorized", 401)
        
        image_id = int(request.match_info["image_id"])
        image = self.plugin.db.get_image_by_id(image_id)
        if not image:
            return self._err("图片不存在", 404)
        
        try:
            data = await request.json()
            confirmed = 1 if data.get("confirmed", True) else 0
            self.plugin.db.update_confirmed(image_id, confirmed)
            return self._ok({"confirmed": confirmed})
        except Exception as e:
            logger.error(f"[CollectImage WebUI] 更新确认状态失败: {e}")
            return self._err(f"更新确认状态失败: {e}")

    async def handle_cleanup(self, request: web.Request) -> web.Response:
        """清理：1)数据库中有记录但文件不存在 2)文件存在但无数据库记录"""
        if not await self._check_auth(request):
            return self._err("Unauthorized", 401)
        
        try:
            data = await request.json() if request.can_read_body else {}
            cleanup_type = data.get("type", "all")
            
            results = {}
            
            # 1. 清理数据库中有记录但文件不存在
            if cleanup_type in ("db", "all"):
                db_cleaned = self.plugin.db.cleanup_missing_files()
                results["db_cleaned"] = db_cleaned
            
            # 2. 清理文件存在但无数据库记录
            if cleanup_type in ("files", "all"):
                files_cleaned = self.plugin.db.cleanup_orphaned_files(self.plugin.images_dir)
                results["files_cleaned"] = files_cleaned
            
            total = results.get("db_cleaned", 0) + results.get("files_cleaned", 0)
            return self._ok({
                "cleaned": total,
                "details": results,
                "message": f"已清理 {total} 条记录 (数据库:{results.get('db_cleaned', 0)}, 文件:{results.get('files_cleaned', 0)})"
            })
        except Exception as e:
            logger.error(f"[CollectImage] 清理失败: {e}")
            return self._err(str(e))

    async def handle_get_stats(self, request: web.Request) -> web.Response:
        try:
            days = int(request.query.get("days", 7))
            if days not in [7, 15, 30]:
                days = 7
            stats = self.plugin.db.get_stats(days)
            return self._ok(stats)
        except Exception as e:
            return self._err(str(e))

    async def handle_health_check(self, request: web.Request) -> web.Response:
        return self._ok({"status": "ok"})

    async def handle_upload_image(self, request: web.Request) -> web.Response:
        """上传图片文件进行分析"""
        try:
            reader = await request.multipart()
            field = await reader.next()
            if field.name != 'file':
                return self._err("无效的文件字段")
            
            filename = field.filename
            if not filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')):
                return self._err("不支持的文件格式，请上传 JPG/PNG/GIF/WebP/BMP 图片")
            
            file_data = b''
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                file_data += chunk
            
            if len(file_data) > 50 * 1024 * 1024:
                return self._err("文件大小超过50MB限制")
            
            import hashlib
            from PIL import Image
            file_hash = hashlib.md5(file_data).hexdigest()
            
            if self.plugin.db.is_hash_exists(file_hash):
                return self._err("图片已存在（重复上传）")
            
            timestamp = int(time.time())
            ext = os.path.splitext(filename)[1] or '.jpg'
            image_filename = f"{timestamp}_webui_upload{ext}"
            image_path = os.path.join(self.plugin.images_dir, image_filename)
            
            with open(image_path, 'wb') as f:
                f.write(file_data)
            
            try:
                tags = {}
                description = ""
                
                char_result = await self.plugin.recognize_character_from_file(image_path)
                all_results = char_result.get("all_results", [])
                ai_detect = char_result.get("ai_detect", "")
                character = self.plugin._extract_characters(all_results)
                
                person_count = len(all_results)
                confirmed_count = sum(1 for r in all_results if not r.get("not_confident", False))
                confirmed = 1 if (person_count > 0 and confirmed_count == person_count) else 0
                
                image_data = {
                    'file_hash': file_hash,
                    'file_path': image_path,
                    'file_name': image_filename,
                    'group_id': 'webui',
                    'sender_id': 'manual',
                    'timestamp': timestamp,
                    'tags': json.dumps(tags, ensure_ascii=False),
                    'character': character,
                    'description': description,
                    'ai_detect': ai_detect,
                    'confirmed': confirmed,
                    'created_at': timestamp
                }
                
                if self.plugin.db.add_image(image_data):
                    return self._ok({
                        "message": "图片导入成功",
                        "image_id": self.plugin.db.get_image_by_hash(file_hash).get('id'),
                        "file_name": image_filename
                    })
                else:
                    os.remove(image_path)
                    return self._err("保存到数据库失败")
            except Exception as e:
                logger.error(f"[CollectImage] 处理图片失败: {e}")
                if os.path.exists(image_path):
                    os.remove(image_path)
                return self._err(f"处理图片失败: {str(e)}")
                
        except Exception as e:
            logger.error(f"[CollectImage] 文件上传失败: {e}")
            return self._err(f"上传失败: {str(e)}")

    async def handle_get_config(self, request: web.Request) -> web.Response:
        """获取当前配置"""
        try:
            config_dict = {}
            for key in self.plugin.config:
                config_dict[key] = self.plugin.config.get(key)
            return self._ok(config_dict)
        except Exception as e:
            return self._err(str(e))

    async def handle_update_config(self, request: web.Request) -> web.Response:
        """更新配置"""
        try:
            data = await request.json()
            
            # 更新配置
            for key, value in data.items():
                if key in self.plugin.config:
                    self.plugin.config[key] = value
            
            # 保存配置文件
            config_path = os.path.join(self.plugin.plugin_dir, "config.json")
            if os.path.exists(config_path):
                with open(config_path, "w", encoding="utf-8") as f:
                    import json
                    json.dump(dict(self.plugin.config), f, ensure_ascii=False, indent=2)
            
            return self._ok({"message": "配置已保存，插件将重启生效"})
        except Exception as e:
            logger.error(f"[CollectImage] 保存配置失败: {e}")
            return self._err(str(e))

    async def handle_get_config_schema(self, request: web.Request) -> web.Response:
        """获取配置定义"""
        try:
            schema_path = os.path.join(self.plugin.plugin_dir, "_conf_schema.json")
            if os.path.exists(schema_path):
                with open(schema_path, "r", encoding="utf-8") as f:
                    import json
                    schema = json.load(f)
                return self._ok(schema)
            return self._err("配置定义文件不存在")
        except Exception as e:
            return self._err(str(e))

    async def handle_index(self, request: web.Request) -> web.Response:
        index_file = self.static_dir / "index.html"
        if index_file.exists():
            return web.FileResponse(index_file)
        return web.Response(text="index.html not found", status=404)

    async def handle_favicon(self, request: web.Request) -> web.Response:
        return web.Response(text="", status=204)

    async def handle_web_static(self, request: web.Request) -> web.Response:
        path = request.match_info["path"]
        file_path = self.static_dir / path
        if file_path.exists() and file_path.is_file():
            return web.FileResponse(file_path)
        return web.Response(text="Not found", status=404)

    async def handle_images_static(self, request: web.Request) -> web.Response:
        try:
            path = request.match_info["path"]
            file_path = Path(self.images_dir) / path
            
            if not file_path.exists() or not file_path.is_file():
                logger.warning(f"[CollectImage] 图片不存在: {file_path}")
                return web.Response(text="Not found", status=404)
            
            size = request.query.get("size", "original")
            
            if size == "thumb":
                logger.info(f"[CollectImage] 请求缩略图: {file_path}")
                thumbnail_size = getattr(self.plugin.config, 'thumbnail_size', DEFAULT_THUMBNAIL_SIZE)
                thumbnail_data = _generate_thumbnail_cached(str(file_path), thumbnail_size)
                
                if thumbnail_data:
                    return web.Response(
                        body=thumbnail_data,
                        content_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"}
                    )
                else:
                    return web.Response(text="Failed to generate thumbnail", status=500)
            
            logger.info(f"[CollectImage] 请求图片: {file_path}")
            return web.FileResponse(file_path)
        except Exception as e:
            logger.error(f"[CollectImage] 加载图片失败: {e}")
            return web.Response(text=str(e), status=500)

    async def handle_list_aliases(self, request: web.Request) -> web.Response:
        """获取别名列表"""
        if not await self._check_auth(request):
            return self._err("Unauthorized", 401)
        
        alias_type = request.query.get("type")
        search = request.query.get("search")
        page = int(request.query.get("page", 1))
        page_size = int(request.query.get("page_size", 25))
        
        if page < 1:
            page = 1
        if page_size not in [25, 50, 100]:
            page_size = 25
        
        offset = (page - 1) * page_size
        
        try:
            if search:
                all_aliases = self.plugin.db.search_alias(search)
            elif alias_type:
                all_aliases = self.plugin.db.get_aliases_by_type(alias_type)
            else:
                all_aliases = self.plugin.db.get_all_aliases()
            
            total = len(all_aliases)
            total_pages = (total + page_size - 1) // page_size
            paginated_aliases = all_aliases[offset:offset + page_size]
            
            return self._ok({
                "aliases": paginated_aliases, 
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages
            })
        except Exception as e:
            logger.error(f"[CollectImage] 获取别名列表失败: {e}")
            return self._err(str(e))

    async def handle_add_alias(self, request: web.Request) -> web.Response:
        """添加别名"""
        if not await self._check_auth(request):
            return self._err("Unauthorized", 401)
        
        try:
            data = await request.json()
            alias_type = data.get("alias_type", "character")
            original_name = data.get("original_name", "")
            alias = data.get("alias", "")
            
            if not original_name or not alias:
                return self._err("缺少必要参数")
            
            success = self.plugin.db.add_alias(alias_type, original_name, alias)
            if success:
                return self._ok({"message": "添加成功"})
            else:
                return self._err("添加失败，可能已存在")
        except Exception as e:
            logger.error(f"[CollectImage] 添加别名失败: {e}")
            return self._err(str(e))

    async def handle_delete_alias(self, request: web.Request) -> web.Response:
        """删除别名"""
        if not await self._check_auth(request):
            return self._err("Unauthorized", 401)
        
        try:
            alias_id = int(request.match_info["alias_id"])
            success = self.plugin.db.delete_alias(alias_id)
            if success:
                return self._ok({"message": "删除成功"})
            else:
                return self._err("删除失败")
        except Exception as e:
            logger.error(f"[CollectImage] 删除别名失败: {e}")
            return self._err(str(e))

    async def handle_import_aliases(self, request: web.Request) -> web.Response:
        """批量导入别名"""
        if not await self._check_auth(request):
            return self._err("Unauthorized", 401)
        
        if self._import_state["running"]:
            return self._err("导入正在进行中")
        
        try:
            import json
            import os
            import asyncio
            
            aliases_path = os.path.join(self.plugin.plugin_dir, "aliases.json")
            
            if not os.path.exists(aliases_path):
                return self._err("aliases.json 文件不存在")
            
            with open(aliases_path, 'r', encoding='utf-8') as f:
                aliases_data = json.load(f)
            
            all_aliases = []
            for alias_type, aliases_dict in aliases_data.items():
                if alias_type in ("description", "version"):
                    continue
                if isinstance(aliases_dict, dict):
                    for original_name, alias_list in aliases_dict.items():
                        if isinstance(alias_list, list):
                            for alias in alias_list:
                                if alias:
                                    all_aliases.append((alias_type, original_name, alias))
            
            total = len(all_aliases)
            self._import_state = {
                "running": True,
                "total": total,
                "imported": 0,
                "stop_requested": False
            }
            
            asyncio.create_task(self._run_import(all_aliases))
            
            return self._ok({"message": f"开始导入 {total} 个别名"})
        except Exception as e:
            logger.error(f"[CollectImage] 导入别名失败: {e}")
            return self._err(str(e))

    async def _run_import(self, all_aliases: list):
        """异步执行导入"""
        imported = 0
        batch_size = 100
        
        for i in range(0, len(all_aliases), batch_size):
            if self._import_state["stop_requested"]:
                logger.info("[CollectImage] 导入已停止")
                break
            
            batch = all_aliases[i:i + batch_size]
            for alias_type, original_name, alias in batch:
                if self._import_state["stop_requested"]:
                    break
                try:
                    self.plugin.db.add_alias(alias_type, original_name, alias)
                    imported += 1
                except:
                    pass
            
            self._import_state["imported"] = imported
            
            await asyncio.sleep(0.5)
        
        self._import_state["running"] = False
        self._import_state["imported"] = imported
        logger.info(f"[CollectImage] 导入完成，共 {imported} 个别名")

    async def handle_import_status(self, request: web.Request) -> web.Response:
        """获取导入状态"""
        if not await self._check_auth(request):
            return self._err("Unauthorized", 401)
        
        return self._ok({
            "running": self._import_state["running"],
            "total": self._import_state["total"],
            "imported": self._import_state["imported"],
            "progress": round(self._import_state["imported"] / self._import_state["total"] * 100, 1) if self._import_state["total"] > 0 else 0
        })

    async def handle_import_stop(self, request: web.Request) -> web.Response:
        """停止导入"""
        if not await self._check_auth(request):
            return self._err("Unauthorized", 401)
        
        if not self._import_state["running"]:
            return self._err("没有正在进行的导入")
        
        self._import_state["stop_requested"] = True
        return self._ok({"message": "已请求停止导入"})

    async def start(self):
        if self._started:
            return
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()
        self._started = True
        logger.info(f"[CollectImage] WebUI 已启动: http://{self.host}:{self.port}, 图片目录: {self.images_dir}")

    async def stop(self):
        if not self._started:
            return
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        self._started = False
        logger.info("[CollectImage] WebUI 已停止")


import json

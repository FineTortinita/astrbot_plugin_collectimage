import asyncio
import hashlib
import os
import secrets
import time
from pathlib import Path
from typing import Any, Optional

from aiohttp import web

from astrbot.api import logger


class WebServer:
    CLIENT_MAX_SIZE = 50 * 1024 * 1024
    SESSION_TIMEOUT = 3600

    def __init__(self, plugin: Any, host: str = "0.0.0.0", port: int = 9192):
        self.plugin = plugin
        self.host = host
        self.port = port
        self.app = web.Application(
            client_max_size=self.CLIENT_MAX_SIZE,
            middlewares=[self._error_middleware, self._auth_middleware],
        )
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self._started = False

        self.static_dir = Path(__file__).parent / "web"
        self.images_dir = str(self.plugin.images_dir)
        logger.info(f"[CollectImage] WebUI 图片目录: {self.images_dir}")

        self._cookie_name = "collectimage_webui_session"
        self._sessions: dict[str, float] = {}
        
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
        self.app.router.add_get("/api/images/{image_id}", self.handle_get_image)
        self.app.router.add_put("/api/images/{image_id}", self.handle_update_image)
        self.app.router.add_delete("/api/images/{image_id}", self.handle_delete_image)
        self.app.router.add_post("/api/images/{image_id}/reanalyze", self.handle_reanalyze)
        self.app.router.add_post("/api/images/{image_id}/recognize_character", self.handle_recognize_character)

        self.app.router.add_get("/api/aliases", self.handle_list_aliases)
        self.app.router.add_post("/api/aliases", self.handle_add_alias)
        self.app.router.add_delete("/api/aliases/{alias_id}", self.handle_delete_alias)
        self.app.router.add_post("/api/aliases/import", self.handle_import_aliases)
        self.app.router.add_get("/api/aliases/import/status", self.handle_import_status)
        self.app.router.add_post("/api/aliases/import/stop", self.handle_import_stop)

        self.app.router.add_post("/api/maintenance/cleanup", self.handle_cleanup)
        self.app.router.add_get("/api/stats", self.handle_get_stats)
        self.app.router.add_get("/api/health", self.handle_health_check)

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
            data = await request.json()
            password = data.get("password", "")
            expected_password = getattr(self.plugin.config, "webui_password", "") or "admin123"
            
            if password == expected_password:
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
            return self._err("密码错误", 401)
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
        limit = int(request.query.get("limit", 50))
        offset = int(request.query.get("offset", 0))

        images = self.plugin.db.search_images(
            tag=tag,
            character=character,
            description=description,
            group_id=group_id,
            limit=limit,
            offset=offset,
        )
        total = self.plugin.db.count_images()
        
        for img in images:
            if img.get("tags"):
                try:
                    img["tags"] = json.loads(img["tags"])
                except:
                    pass
        return self._ok({"images": images, "total": total})

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
        total = self.plugin.db.count_images()
        return self._ok({"total": total})

    async def handle_health_check(self, request: web.Request) -> web.Response:
        return self._ok({"status": "ok"})

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
            logger.info(f"[CollectImage] 请求图片: {file_path}")
            if file_path.exists() and file_path.is_file():
                return web.FileResponse(file_path)
            logger.warning(f"[CollectImage] 图片不存在: {file_path}")
            return web.Response(text="Not found", status=404)
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

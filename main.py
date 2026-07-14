import asyncio
import base64
import hashlib
import ipaddress
import json
import os
import random
import re
import shutil
import tempfile
import time
import uuid
from io import BytesIO
from typing import Optional
from urllib.parse import urljoin, urlparse

import aiohttp
from aiohttp.abc import AbstractResolver
from aiohttp.resolver import DefaultResolver
from PIL import Image as PILImage
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.event.filter import EventMessageType
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.core.message.components import Image, Forward

from .database import Database


def _is_public_ip(address: str) -> bool:
    """Only allow globally routable addresses for remote image downloads."""
    try:
        return ipaddress.ip_address(address).is_global
    except ValueError:
        return False


def _normalize_allowed_groups(values: object) -> set[str]:
    if not isinstance(values, (list, tuple, set)):
        return set()
    return {str(item).strip() for item in values if str(item).strip()}


class PublicOnlyResolver(AbstractResolver):
    """Resolve hosts once and reject DNS answers containing non-public IPs."""

    def __init__(self, resolver=None):
        self._resolver = resolver or DefaultResolver()

    async def resolve(self, host: str, port: int = 0, family: int = 0):
        records = await self._resolver.resolve(host, port, family)
        if not records:
            raise OSError(f"无法解析远程主机: {host}")
        if any(not _is_public_ip(record["host"]) for record in records):
            raise OSError(f"远程主机解析到非公网地址: {host}")
        return records

    async def close(self):
        await self._resolver.close()


@register("astrbot_plugin_collectimage", "FineTortinita", "群聊图片收集插件", "v1.8.0")
class CollectImagePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.plugin_dir = str(StarTools.get_data_dir("astrbot_plugin_collectimage"))
        os.makedirs(self.plugin_dir, exist_ok=True)
        
        # 迁移旧数据
        self._migrate_old_data()
        
        self.images_dir = os.path.join(self.plugin_dir, "images")
        os.makedirs(self.images_dir, exist_ok=True)
        
        self.db = Database(self.plugin_dir)
        self.tags_library = self._load_tags_library()
        
        # 图片处理队列 - 串行处理所有图片
        self._image_queue = asyncio.Queue()
        self._worker_task = None
        self._init_task = None
        self._queued_image_ids: set = set()
        self._replied_message_ids: set = set()
        
        self.web_server = None
        self._init_web_server()
        
        # 异步初始化
        self._init_task = asyncio.create_task(self._init_async())
        
        logger.info(f"[CollectImage] 插件已加载，数据目录: {self.plugin_dir}")
    
    def _migrate_old_data(self):
        """迁移旧数据到新目录"""
        import shutil
        old_data_dir = os.path.dirname(__file__)
        
        # 检查旧目录是否存在数据库或图片目录
        old_db_path = os.path.join(old_data_dir, "collectimage.db")
        old_images_dir = os.path.join(old_data_dir, "images")
        old_aliases_path = os.path.join(old_data_dir, "aliases.json")
        
        new_db_path = os.path.join(self.plugin_dir, "collectimage.db")
        new_images_dir = os.path.join(self.plugin_dir, "images")
        new_aliases_path = os.path.join(self.plugin_dir, "aliases.json")
        
        migrated = False
        
        # 迁移数据库：旧文件存在且新文件不存在或新文件为空
        if os.path.exists(old_db_path):
            new_db_exists = os.path.exists(new_db_path)
            new_db_empty = new_db_exists and os.path.getsize(new_db_path) == 0
            if not new_db_exists or new_db_empty:
                try:
                    shutil.copy2(old_db_path, new_db_path)
                    logger.info(f"[CollectImage] 已迁移数据库: {old_db_path} -> {new_db_path}")
                    migrated = True
                except Exception as e:
                    logger.error(f"[CollectImage] 迁移数据库失败: {e}")
        
        # 迁移图片目录
        if os.path.exists(old_images_dir) and not os.path.exists(new_images_dir):
            try:
                shutil.copytree(old_images_dir, new_images_dir)
                logger.info(f"[CollectImage] 已迁移图片目录: {old_images_dir} -> {new_images_dir}")
                migrated = True
            except Exception as e:
                logger.error(f"[CollectImage] 迁移图片目录失败: {e}")
        
        # 迁移别名文件
        if os.path.exists(old_aliases_path):
            new_aliases_exists = os.path.exists(new_aliases_path)
            new_aliases_empty = new_aliases_exists and os.path.getsize(new_aliases_path) == 0
            if not new_aliases_exists or new_aliases_empty:
                try:
                    shutil.copy2(old_aliases_path, new_aliases_path)
                    logger.info(f"[CollectImage] 已迁移别名文件: {old_aliases_path} -> {new_aliases_path}")
                    migrated = True
                except Exception as e:
                    logger.error(f"[CollectImage] 迁移别名文件失败: {e}")
        
        if migrated:
            logger.info("[CollectImage] 数据迁移完成")

    async def _init_async(self):
        """异步初始化 - 启动队列处理器"""
        # 启动图片处理 worker
        self._worker_task = asyncio.create_task(self._image_worker())
        
        # 初始化别名
        await self._init_aliases_async()
    
    async def _image_worker(self):
        """图片处理 worker - 串行处理队列中的图片"""
        logger.info("[CollectImage] 图片处理队列已启动")
        while True:
            task = await self._image_queue.get()
            
            if task is None:  # 退出信号
                logger.info("[CollectImage] 图片处理队列已停止")
                break
            
            try:
                await self._process_image_task(task)
            except Exception as e:
                logger.error(f"[CollectImage] 处理图片失败: {e}")
            finally:
                self._image_queue.task_done()
    
    async def _process_image_task(self, task):
        """处理队列中的图片"""
        task_type = task.get('type')
        
        try:
            if task_type == 'single':
                await self._do_process_single_image(task)
            elif task_type == 'forward':
                await self._do_process_forward_image(task)
            else:
                logger.warning(f"[CollectImage] 未知任务类型: {task_type}")
        finally:
            image_id = task.get('image_id', '')
            if image_id:
                self._queued_image_ids.discard(image_id)
    
    async def _do_process_single_image(self, task):
        """处理普通图片"""
        event = task['event']
        group_id = task['group_id']
        sender_id = task['sender_id']
        local_path = task.get('local_path')
        cleanup_path = task.get('cleanup_path')
        image_url = local_path
        saved_image_path = None
        db_inserted = False
        
        try:
            if not local_path:
                logger.warning("[CollectImage] 无法获取图片本地文件，跳过")
                return
            
            size_check = self._check_image_size(local_path)
            if size_check is None:
                return
            if not size_check:
                logger.info("[CollectImage] 图片尺寸过小，跳过")
                return
            
            file_hash = self._calculate_hash(local_path)
            
            if self.db.is_hash_exists(file_hash):
                logger.info("[CollectImage] 图片已存在 (MD5)，跳过")
                await self._reply_duplicate(event, group_id)
                return
            
            # 先 VLM 分析，无效则不保存
            if image_url:
                result = await self.analyze_image(image_url, event)
                
                if result.get("filter_result") != "有效":
                    logger.info(f"[CollectImage] 图片无效，跳过: {result.get('reason')}")
                    return
                
                # VLM 有效后再保存图片
                timestamp = int(time.time())
                ext = self._detect_image_extension(local_path)
                image_filename = self._make_image_filename(ext)
                image_path = os.path.join(self.images_dir, image_filename)
                self._copy_image_exclusive(local_path, image_path)
                saved_image_path = image_path
                logger.info(f"[CollectImage] 图片已保存: {image_path}")
                
                # AnimeTrace 识别
                char_result = await self.recognize_character_from_file(local_path)
                all_results = char_result.get("all_results", [])
                ai_detect = char_result.get("ai_detect", "")
                
                person_count = len(all_results)
                confirmed_count = sum(1 for r in all_results if not r.get("not_confident", False))
                not_confident_count = person_count - confirmed_count
                confirmed = 1 if confirmed_count > 0 and not_confident_count == 0 else 0
                
                character = self._extract_characters(all_results)
                # 更健壮的 ai_detect 类型检查
                ai_detect = "true" if str(ai_detect).lower() in ("true", "1", "yes") else "false"
                
                inserted = self.db.insert_image(
                    file_hash=file_hash,
                    file_path=image_path,
                    file_name=image_filename,
                    group_id=str(group_id),
                    sender_id=str(sender_id),
                    timestamp=timestamp,
                    tags=result.get("tags"),
                    character=character,
                    description=result.get("description"),
                    ai_detect=ai_detect,
                    confirmed=confirmed,
                    phash=None,
                )
                db_inserted = inserted
                if not inserted:
                    try:
                        os.remove(image_path)
                    except FileNotFoundError:
                        pass
                    raise RuntimeError("图片数据库记录写入失败")
                logger.info(f"[CollectImage] 分析完成: 人数={person_count}, 已确认={confirmed_count}, 未确认={not_confident_count}, 角色={character}, AI检测={ai_detect}")

        except Exception as e:
            if saved_image_path and not db_inserted and os.path.exists(saved_image_path):
                try:
                    os.remove(saved_image_path)
                except OSError:
                    pass
            logger.error(f"[CollectImage] 处理单图失败: {e}")
        finally:
            if cleanup_path and os.path.exists(cleanup_path):
                try:
                    os.remove(cleanup_path)
                except OSError as e:
                    logger.debug(f"[CollectImage] 清理临时图片失败: {cleanup_path}, {e}")

    async def _get_single_image_file_path(self, msg: Image) -> tuple[Optional[str], Optional[str]]:
        """获取插件自有临时图片路径，避免 AstrBot 事件临时文件被清理。"""
        try:
            local_path = await msg.convert_to_file_path()
            if local_path and os.path.exists(local_path):
                return self._copy_to_owned_temp(local_path)
            if local_path:
                logger.warning(f"[CollectImage] 图片临时文件不存在，尝试重新下载: {local_path}")
        except Exception as e:
            logger.warning(f"[CollectImage] 获取图片本地路径失败，尝试重新下载: {e}")

        image_url = msg.url or msg.file or ""
        if not image_url.startswith(("http://", "https://")):
            return None, None

        try:
            tmp_path = await self._download_image_safely(image_url)
            return tmp_path, tmp_path
        except Exception as e:
            logger.error(f"[CollectImage] 重新下载图片异常: {e}")
            return None, None

    def _copy_to_owned_temp(self, source_path: str) -> tuple[str, str]:
        suffix = os.path.splitext(source_path)[1] or ".jpg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
        shutil.copy(source_path, tmp_path)
        return tmp_path, tmp_path

    def _is_safe_url(self, url: str) -> bool:
        """Perform the non-DNS part of remote URL validation."""
        try:
            parsed = urlparse(url)
            if parsed.scheme.lower() not in ("http", "https"):
                return False
            if parsed.username or parsed.password or not parsed.hostname:
                return False

            hostname = parsed.hostname.rstrip(".").lower()
            if hostname in ("localhost", "localhost.localdomain"):
                return False
            if hostname.endswith((".local", ".internal")):
                return False

            try:
                return ipaddress.ip_address(hostname).is_global
            except ValueError:
                return True
        except (TypeError, ValueError):
            return False

    async def _download_image_safely(self, url: str) -> str:
        """Download an image with DNS, redirect, byte and pixel limits."""
        if not self._is_safe_url(url):
            raise ValueError("不安全的图片URL")

        max_bytes = self._get_positive_int_config("max_download_size_mb", 10) * 1024 * 1024
        max_pixels = self._get_positive_int_config("max_image_pixels", 40_000_000)
        timeout = aiohttp.ClientTimeout(total=30, connect=10, sock_read=15)
        connector = aiohttp.TCPConnector(
            resolver=PublicOnlyResolver(),
            ttl_dns_cache=0,
        )
        current_url = url

        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            for _ in range(4):
                if not self._is_safe_url(current_url):
                    raise ValueError("重定向目标不安全")

                async with session.get(current_url, allow_redirects=False) as response:
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location:
                            raise ValueError("重定向缺少Location")
                        current_url = urljoin(current_url, location)
                        continue

                    if response.status != 200:
                        raise ValueError(f"图片下载失败 HTTP {response.status}")

                    if response.content_length is not None and response.content_length > max_bytes:
                        raise ValueError("图片超过下载大小限制")

                    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                    if content_type and not (
                        content_type.startswith("image/")
                        or content_type == "application/octet-stream"
                    ):
                        raise ValueError(f"远程内容不是图片: {content_type}")

                    suffix = os.path.splitext(urlparse(current_url).path)[1].lower()
                    if suffix not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
                        suffix = ".img"

                    tmp_path = None
                    try:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                            tmp_path = tmp.name
                            total = 0
                            async for chunk in response.content.iter_chunked(64 * 1024):
                                total += len(chunk)
                                if total > max_bytes:
                                    raise ValueError("图片超过下载大小限制")
                                tmp.write(chunk)

                        with PILImage.open(tmp_path) as image:
                            width, height = image.size
                            if width <= 0 or height <= 0 or width * height > max_pixels:
                                raise ValueError("图片像素数量超过限制")
                            image.verify()

                        return tmp_path
                    except Exception:
                        if tmp_path and os.path.exists(tmp_path):
                            os.remove(tmp_path)
                        raise

        raise ValueError("图片重定向次数过多")

    async def _do_process_forward_image(self, task):
        """处理转发消息中的图片"""
        image_url = task['image_url']
        event = task['event']
        group_id = task['group_id']
        sender_id = task['sender_id']
        
        logger.info(f"[CollectImage] 处理转发图片: {image_url}")
        tmp_path = None
        saved_image_path = None
        db_inserted = False

        try:
            tmp_path = await self._download_image_safely(image_url)
            file_hash = self._calculate_hash(tmp_path)

            if self.db.is_hash_exists(file_hash):
                logger.info("[CollectImage] 转发图片已存在 (MD5)，跳过")
                await self._reply_duplicate(event, group_id)
                return

            size_check = self._check_image_size(tmp_path)
            if size_check is None:
                return
            if not size_check:
                logger.info("[CollectImage] 转发图片尺寸过小，跳过")
                return

            result = await self.analyze_image(tmp_path, event)
            if result.get("filter_result") != "有效":
                logger.info(f"[CollectImage] 转发图片无效，跳过: {result.get('reason')}")
                return

            timestamp = int(time.time())
            file_ext = self._detect_image_extension(tmp_path)
            image_filename = self._make_image_filename(file_ext)
            image_path = os.path.join(self.images_dir, image_filename)
            self._copy_image_exclusive(tmp_path, image_path)
            saved_image_path = image_path
            logger.info(f"[CollectImage] 转发图片已保存: {image_path}")

            char_result = await self.recognize_character_from_file(tmp_path)
            all_results = char_result.get("all_results", [])
            ai_detect = char_result.get("ai_detect", "")

            person_count = len(all_results)
            confirmed_count = sum(1 for r in all_results if not r.get("not_confident", False))
            not_confident_count = person_count - confirmed_count
            confirmed = 1 if confirmed_count > 0 and not_confident_count == 0 else 0
            character = self._extract_characters(all_results)
            ai_detect = "true" if str(ai_detect).lower() in ("true", "1", "yes") else "false"

            inserted = self.db.insert_image(
                file_hash=file_hash,
                file_path=image_path,
                file_name=image_filename,
                group_id=str(group_id),
                sender_id=str(sender_id),
                timestamp=timestamp,
                tags=result.get("tags"),
                character=character,
                description=result.get("description"),
                ai_detect=ai_detect,
                confirmed=confirmed,
                phash=None,
            )
            db_inserted = inserted
            if not inserted:
                try:
                    os.remove(image_path)
                except FileNotFoundError:
                    pass
                raise RuntimeError("图片数据库记录写入失败")

            logger.info(f"[CollectImage] 转发图片分析完成: 人数={person_count}, 已确认={confirmed_count}, 未确认={not_confident_count}, 角色={character}, AI检测={ai_detect}")
        except Exception as e:
            if saved_image_path and not db_inserted and os.path.exists(saved_image_path):
                try:
                    os.remove(saved_image_path)
                except OSError:
                    pass
            logger.error(f"[CollectImage] 处理转发图片失败: {e}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    async def _init_aliases_async(self):
        """异步初始化别名库"""
        # 先检查数据目录，再检查插件代码目录
        aliases_path = os.path.join(self.plugin_dir, "aliases.json")
        if not os.path.exists(aliases_path):
            plugin_code_dir = os.path.dirname(__file__)
            aliases_path = os.path.join(plugin_code_dir, "aliases.json")
        
        if not os.path.exists(aliases_path):
            logger.info("[CollectImage] 别名库文件不存在，跳过导入")
            return
        
        try:
            with open(aliases_path, 'r', encoding='utf-8') as f:
                aliases_data = json.load(f)
            
            if not aliases_data.get("character") and not aliases_data.get("work"):
                logger.info("[CollectImage] 别名库为空，跳过导入")
                return
            
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
            current_count = self.db.get_alias_count()
            
            if current_count >= total:
                logger.info(f"[CollectImage] 数据库已有 {current_count} 个别名，无需导入")
                return
            
            logger.info(f"[CollectImage] 开始异步导入 {total} 个别名（当前已有 {current_count}）...")
            
            imported = 0
            batch_size = 100
            
            for i in range(0, len(all_aliases), batch_size):
                batch = all_aliases[i:i + batch_size]
                for alias_type, original_name, alias in batch:
                    try:
                        if self.db.add_alias(alias_type, original_name, alias):
                            imported += 1
                    except Exception:
                        pass
                
                await asyncio.sleep(0.5)
            
            logger.info(f"[CollectImage] 异步导入完成，新增 {imported} 个别名")
        except Exception as e:
            logger.error(f"[CollectImage] 导入别名失败: {e}")

    def _init_web_server(self):
        webui_enabled = getattr(self.config, 'webui_enabled', False)
        if webui_enabled:
            try:
                from .web_server import WebServer
                password = str(getattr(self.config, 'webui_password', '') or '')
                if not password or password == "admin123":
                    logger.error("[CollectImage] WebUI 未启动：请先设置非默认访问密码")
                    return
                port = getattr(self.config, 'webui_port', 9192)
                host = getattr(self.config, 'webui_host', '127.0.0.1')
                self.web_server = WebServer(self, host=host, port=port)
                asyncio.create_task(self.web_server.start())
            except Exception as e:
                logger.error(f"[CollectImage] 启动 WebUI 失败: {e}")

    async def _get_provider_id(self, event=None) -> str:
        configured_id = (getattr(self.config, 'llm_provider_id', '') or '').strip()
        if configured_id:
            try:
                provider = self.context.get_provider_by_id(provider_id=configured_id)
                if provider:
                    return configured_id
            except Exception:
                logger.warning(f"[CollectImage] 配置的 Provider '{configured_id}' 不可用，尝试回退")

        if event:
            try:
                return await self.context.get_current_chat_provider_id(umo=event.unified_msg_origin)
            except Exception:
                pass

        try:
            return await self.context.get_current_chat_provider_id(umo="default")
        except Exception:
            pass

        try:
            all_providers = self.context.get_all_providers()
            if all_providers:
                return all_providers[0].meta().id
        except Exception:
            pass

        return None

    async def _reply_duplicate(self, event, group_id):
        probability = getattr(self.config, 'duplicate_reply_probability', 0)
        if probability <= 0:
            return

        message_id = getattr(event.message_obj, 'message_id', None)
        if not message_id:
            return

        if message_id in self._replied_message_ids:
            return

        if random.randint(1, 100) > probability:
            return

        reply_messages = getattr(self.config, 'duplicate_reply_messages', [])
        if not reply_messages:
            return

        reply_text = random.choice(reply_messages)

        try:
            bot = getattr(event, 'bot', None)
            if not bot or not hasattr(bot, 'api'):
                return

            await bot.api.call_action(
                'send_group_msg',
                group_id=int(group_id),
                message=[
                    {"type": "reply", "data": {"id": str(message_id)}},
                    {"type": "text", "data": {"text": reply_text}}
                ]
            )
            self._replied_message_ids.add(message_id)
            if len(self._replied_message_ids) > 1000:
                self._replied_message_ids.clear()
            logger.info(f"[CollectImage] 已回复重复图片: {reply_text}")
        except Exception as e:
            logger.error(f"[CollectImage] 回复重复图片失败: {e}")

    def _load_tags_library(self) -> dict:
        plugin_code_dir = os.path.dirname(__file__)
        tags_path = os.path.join(plugin_code_dir, "tags_library.json")
        try:
            with open(tags_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[CollectImage] 加载 tag 库失败: {e}")
            return {}

    def _build_tags_prompt(self) -> str:
        prompt_parts = ["以下是可选的标签分类：\n"]
        for category, tags in self.tags_library.items():
            tag_list = [f"{t['name']}({t['cn']})" for t in tags]
            prompt_parts.append(f"\n{category}: {', '.join(tag_list)}")
        return "".join(prompt_parts)

    def _sanitize_tags(self, tags: object) -> dict:
        if not isinstance(tags, dict):
            return {}
        sanitized = {}
        for category, values in tags.items():
            definitions = self.tags_library.get(category)
            if not isinstance(definitions, list) or not isinstance(values, list):
                continue
            allowed = {
                str(value)
                for definition in definitions
                if isinstance(definition, dict)
                for value in (definition.get("name"), definition.get("cn"))
                if value
            }
            selected = []
            for value in values[:3]:
                value = str(value).strip()
                if value in allowed and value not in selected:
                    selected.append(value)
            sanitized[category] = selected
        return sanitized

    @staticmethod
    def _sanitize_generated_text(value: object, max_length: int) -> str:
        text = str(value or "").replace("\x00", "").strip()
        return text[:max_length]

    def _calculate_hash(self, file_path: str) -> str:
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    @staticmethod
    def _make_image_filename(extension: str) -> str:
        extension = (extension or ".jpg").lower()
        if extension not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
            extension = ".jpg"
        return f"{int(time.time())}_{uuid.uuid4().hex}{extension}"

    @staticmethod
    def _copy_image_exclusive(source_path: str, destination_path: str) -> None:
        with open(source_path, "rb") as source, open(destination_path, "xb") as destination:
            shutil.copyfileobj(source, destination, length=64 * 1024)

    @staticmethod
    def _detect_image_extension(file_path: str) -> str:
        format_extensions = {
            "JPEG": ".jpg",
            "PNG": ".png",
            "GIF": ".gif",
            "WEBP": ".webp",
            "BMP": ".bmp",
        }
        with PILImage.open(file_path) as image:
            return format_extensions.get((image.format or "").upper(), ".jpg")

    def _get_positive_int_config(self, key: str, default: int) -> int:
        try:
            value = getattr(self.config, key, default)
            if isinstance(value, int):
                parsed = value
            elif isinstance(value, str):
                parsed = int(value.strip())
            else:
                parsed = default
            return max(1, parsed)
        except (TypeError, ValueError):
            return default

    def _check_image_size(self, file_path: str) -> Optional[bool]:
        """检查图片尺寸，宽高阈值来自插件配置。"""
        min_width = self._get_positive_int_config('min_image_width', 600)
        min_height = self._get_positive_int_config('min_image_height', 600)
        max_download_bytes = self._get_positive_int_config('max_download_size_mb', 10) * 1024 * 1024
        max_pixels = self._get_positive_int_config('max_image_pixels', 40_000_000)
        try:
            if os.path.getsize(file_path) > max_download_bytes:
                logger.warning(f"[CollectImage] 图片文件超过大小限制，跳过: {file_path}")
                return None
            with PILImage.open(file_path) as img:
                width, height = img.size
                if width <= 0 or height <= 0 or width * height > max_pixels:
                    logger.warning(f"[CollectImage] 图片像素数量超过限制，跳过: {width}x{height}")
                    return None
                if width < min_width or height < min_height:
                    return False
                return True
        except FileNotFoundError:
            logger.warning(f"[CollectImage] 图片文件不存在，跳过: {file_path}")
            return None
        except Exception as e:
            logger.warning(f"[CollectImage] 图片尺寸检查失败: {file_path}, {e}")
            return None

    def _is_sticker(self, img: Image, event: AstrMessageEvent | None = None, img_index: int = 0) -> bool:
        def is_emoji_summary(summary: object) -> bool:
            if not summary:
                return False
            s = str(summary).lower()
            return '表情' in s or 'emoji' in s or 'sticker' in s

        def is_sub_type_emoji(sub_type: object) -> bool:
            if sub_type is None:
                return False
            if sub_type == 1 or sub_type == "1":
                return True
            try:
                return int(sub_type) == 1
            except (ValueError, TypeError):
                return False

        image_segments = None
        if event and hasattr(event, 'message_obj') and hasattr(event.message_obj, 'raw_message'):
            raw_event = event.message_obj.raw_message
            if hasattr(raw_event, 'message') and isinstance(raw_event.message, list):
                image_segments = [
                    seg for seg in raw_event.message
                    if isinstance(seg, dict) and seg.get('type') == 'image'
                ]

        if image_segments and img_index < len(image_segments):
            matched_data = image_segments[img_index].get('data', {}) or {}
            
            sub_type = matched_data.get('sub_type')
            if is_sub_type_emoji(sub_type):
                return True

            summary = matched_data.get('summary', '')
            if is_emoji_summary(summary):
                return True

            if matched_data.get('emoji_id') or matched_data.get('emoji_package_id'):
                return True

            url = matched_data.get('url', '')
            if url:
                url_str = str(url).lower()
                if 'vip.qq.com/club/item/parcel' in url_str or 'gxh.vip.qq.com' in url_str:
                    return True

        if hasattr(img, 'subType') and is_sub_type_emoji(img.subType):
            return True

        if hasattr(img, '__dict__'):
            sub_type_underscore = img.__dict__.get('sub_type')
            if is_sub_type_emoji(sub_type_underscore):
                return True

        try:
            raw_data = img.toDict()
            if isinstance(raw_data, dict) and 'data' in raw_data:
                data = raw_data['data']
                
                sub_type = data.get('sub_type') or data.get('subType')
                if is_sub_type_emoji(sub_type):
                    return True

                summary = data.get('summary', '')
                if is_emoji_summary(summary):
                    return True

                if data.get('emoji_id') or data.get('emoji_package_id'):
                    return True

                img_type = data.get('type') or data.get('imageType') or data.get('image_type')
                if img_type in ['emoji', 'sticker', 'face', 'meme']:
                    return True
        except Exception:
            pass

        if is_sub_type_emoji(getattr(img, 'subType', None)):
            return True
        if is_emoji_summary(getattr(img, 'summary', None)):
            return True
        if getattr(img, 'emoji_id', None) or getattr(img, 'emoji_package_id', None):
            return True

        return False

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent, **kwargs):
        group_id = str(event.get_group_id()).strip()
        allowed_groups = _normalize_allowed_groups(
            self.config.get("allowed_groups", [])
        )

        if not allowed_groups or group_id not in allowed_groups:
            return

        sender_id = event.get_sender_id()

        messages = event.get_messages()
        logger.info(f"[CollectImage] 消息链: 共{len(messages)}条, 类型={[type(m).__name__ for m in messages]}")
        
        for i, msg in enumerate(messages):
            msg_type = type(msg).__name__
            # 处理普通图片
            if isinstance(msg, Image):
                await self._process_single_image(msg, event, group_id, sender_id, i)
            
            # 处理合并转发消息 (Forward 类型)
            elif isinstance(msg, Forward):
                logger.info(f"[CollectImage] 检测到Forward: id={msg.id}")
                await self._process_forward_message(msg.id, event, group_id, sender_id)
            
            else:
                logger.info(f"[CollectImage] 未处理的消息类型: {msg_type}")

    async def _process_forward_message(self, forward_id, event: AstrMessageEvent, group_id: str, sender_id: str) -> None:
        """处理合并转发消息，通过API获取内容"""
        if not forward_id:
            logger.warning("[CollectImage] 转发消息无ID")
            return
        
        bot = getattr(event, 'bot', None)
        if not bot or not hasattr(bot, 'api'):
            logger.warning("[CollectImage] 无法获取 bot 对象")
            return
        
        try:
            logger.info(f"[CollectImage] 调用 get_forward_msg API, id={forward_id}")
            result = await bot.api.call_action('get_forward_msg', id=str(forward_id))
            logger.info(f"[CollectImage] get_forward_msg 返回: {result}")
            
            if not isinstance(result, dict):
                logger.warning(f"[CollectImage] API返回格式错误: {type(result)}")
                return
            
            messages = result.get('messages', [])
            if not messages:
                logger.warning("[CollectImage] 转发消息为空")
                return
            
            logger.info(f"[CollectImage] 转发消息包含 {len(messages)} 个节点")
            
            # 解析每个节点的消息
            for msg_item in messages:
                message_content = msg_item.get('message', [])
                if not isinstance(message_content, list):
                    continue
                
                logger.info(f"[CollectImage] 节点消息内容: {message_content}")
                
                for segment in message_content:
                    seg_type = type(segment).__name__
                    
                    if isinstance(segment, Image):
                        await self._process_single_image(segment, event, group_id, sender_id, 0)
                    elif isinstance(segment, dict) and segment.get('type') == 'image':
                        # 字典格式的图片消息段
                        file_data = segment.get('data', {})
                        file_url = file_data.get('url') or file_data.get('file', '')
                        if file_url:
                            await self._process_image_by_url(file_url, event, group_id, sender_id)
        
        except Exception as e:
            logger.error(f"[CollectImage] 处理转发消息失败: {e}")

    async def _process_image_by_url(self, image_url: str, event: AstrMessageEvent, group_id: str, sender_id: str) -> None:
        if image_url and image_url in self._queued_image_ids:
            logger.info("[CollectImage] 转发图片已在队列中，跳过")
            return
        if image_url:
            self._queued_image_ids.add(image_url)
        await self._image_queue.put({
            'type': 'forward',
            'image_url': image_url,
            'event': event,
            'group_id': group_id,
            'sender_id': sender_id,
            'image_id': image_url,
        })

    async def _process_single_image(self, msg: Image, event: AstrMessageEvent, group_id: str, sender_id: str, img_index: int = 0) -> None:
        image_id = msg.url or msg.file or ""
        if image_id and image_id in self._queued_image_ids:
            logger.info("[CollectImage] 图片已在队列中，跳过")
            return
        if self._is_sticker(msg, event, img_index):
            logger.info("[CollectImage] 跳过表情包")
            return

        if image_id:
            self._queued_image_ids.add(image_id)
        local_path = None
        cleanup_path = None
        queued = False
        try:
            local_path, cleanup_path = await self._get_single_image_file_path(msg)
            if not local_path:
                logger.warning("[CollectImage] 无法获取图片本地文件，跳过")
                return
            original_image_ref = msg.url or msg.file or ""
            image_url = original_image_ref if original_image_ref.startswith(("http://", "https://")) else local_path
            await self._image_queue.put({
                'type': 'single',
                'local_path': local_path,
                'cleanup_path': cleanup_path,
                'image_url': image_url,
                'event': event,
                'group_id': group_id,
                'sender_id': sender_id,
                'image_id': image_id,
            })
            queued = True
        finally:
            if image_id and not queued:
                self._queued_image_ids.discard(image_id)
            if cleanup_path and not queued and os.path.exists(cleanup_path):
                try:
                    os.remove(cleanup_path)
                except OSError as e:
                    logger.debug(f"[CollectImage] 清理未入队临时图片失败: {cleanup_path}, {e}")

    async def _llm_generate_with_retry(self, provider_id: str, prompt: str, image_urls: list, max_retries: int = 2) -> str:
        """带重试逻辑的 LLM 调用"""
        for attempt in range(max_retries + 1):
            try:
                llm_resp = await self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                    image_urls=image_urls,
                )
                return llm_resp.completion_text.strip()
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"[CollectImage] LLM 调用失败 (尝试 {attempt + 1}/{max_retries + 1}): {e}")
                    await asyncio.sleep(1)
                else:
                    raise

    async def _analyze_image_content(self, provider_id: str, image_url: str) -> dict:
        """分析图片内容（标签、角色、描述）"""
        tags_prompt = self._build_tags_prompt()
        match_prompt = f"""{tags_prompt}

请分析这张图片，从上述标签中选择最匹配的标签。
要求：
1. 每个分类最多选择3个最相关的标签
2. 只选择确实存在的特征，不要猜测
3. 必须使用中文标签名返回（如"长发"、"金发"、"连衣裙"）
4. 以JSON格式返回，格式如下：
{{"gender": ["中文标签"], "hair": ["中文标签"], "eyes": ["中文标签"], "clothes": ["中文标签"], "pose": ["中文标签"], "style": ["中文标签"], "expression": ["中文标签"]}}
如果某个分类没有匹配的标签，返回空列表。"""

        tags_text = await self._llm_generate_with_retry(provider_id, match_prompt, [image_url])
        try:
            json_match = re.search(r'\{[^{}]*\}', tags_text, re.DOTALL)
            matched_tags = self._sanitize_tags(
                json.loads(json_match.group()) if json_match else {}
            )
        except (json.JSONDecodeError, ValueError):
            matched_tags = {}

        char_prompt = """请识别这张图片中的角色名称（如果有）。
包括但不限于：动漫角色、游戏角色、原创角色等。
如果无法确定具体角色名，请回答"未知"。
只返回角色名，不要其他解释。"""
        character = self._sanitize_generated_text(
            await self._llm_generate_with_retry(provider_id, char_prompt, [image_url]),
            200,
        )

        desc_prompt = "请用一句话描述这张图片的主要内容，不超过30字。"
        description = self._sanitize_generated_text(
            await self._llm_generate_with_retry(provider_id, desc_prompt, [image_url]),
            500,
        )

        return {"tags": matched_tags, "character": character, "description": description}

    async def analyze_image(self, image_url: str, event: AstrMessageEvent) -> dict:
        try:
            provider_id = await self._get_provider_id(event)

            filter_prompt = getattr(self.config, "filter_prompt", "") or """请判断这张图片是否是有效的绘画素材。
有效：有人物、角色、场景、物品等具体内容的动漫风格绘画、插画 CG、漫画、游戏立绘等人工绘制的图片。
无效：照片、漫画，写实图片、截图、表情包、大段文字、二维码、UI界面、广告图、纯文字图片、模板图等无意义内容。
请直接回答"有效"或"无效"，，无需其他解释。"""

            filter_result = await self._llm_generate_with_retry(provider_id, filter_prompt, [image_url])
            logger.info(f"[CollectImage] 筛选结果: {filter_result}")

            if "无效" in filter_result:
                return {
                    "filter_result": "无效",
                    "reason": filter_result,
                    "tags": [],
                    "character": "",
                    "description": ""
                }

            content = await self._analyze_image_content(provider_id, image_url)
            return {
                "filter_result": "有效",
                "reason": "",
                **content
            }

        except Exception as e:
            logger.error(f"[CollectImage] 分析失败: {e}")
            return {
                "filter_result": "错误",
                "reason": str(e),
                "tags": [],
                "character": "",
                "description": ""
            }

    async def recognize_character(self, image_url: Optional[str] = None, image_base64: Optional[str] = None) -> dict:
        """调用 AnimeTrace API 识别角色，返回完整结果"""
        try:
            async with aiohttp.ClientSession() as session:
                form = aiohttp.FormData()
                
                # 优先使用 base64，其次使用 url
                if image_base64:
                    form.add_field('base64', image_base64)
                elif image_url:
                    form.add_field('url', image_url)
                else:
                    logger.error("[CollectImage] 角色识别缺少图片输入")
                    return {"character": "未知", "ai_detect": "识别失败", "all_results": []}
                
                form.add_field('model', 'animetrace_high_beta')
                form.add_field('is_multi', '1')
                form.add_field('ai_detect', '1')
                
                async with session.post(
                    'https://api.animetrace.com/v1/search', 
                    data=form,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status != 200:
                        logger.error(f"[CollectImage] 角色识别失败 HTTP: {resp.status}")
                        return {"character": "未知", "ai_detect": "识别失败", "all_results": []}
                    
                    result = await resp.json()
                    
                    # code=0 表示成功
                    if result.get("code") != 0:
                        logger.error(f"[CollectImage] 角色识别失败: {result.get('code')}")
                        return {"character": "未知", "ai_detect": str(result.get("code", "")), "all_results": []}
                    
                    # 获取原始结果
                    data = result.get("data", [])
                    ai_detect = str(result.get("ai", ""))
                    
                    # 检查 data 是否为空
                    if not data:
                        logger.warning(f"[CollectImage] 角色识别成功但无结果 (data为空)")
                        return {"character": "未知", "ai_detect": ai_detect, "all_results": []}
                    
                    logger.info(f"[CollectImage] 角色识别成功，共 {len(data)} 个结果, AI检测: {ai_detect}")
                    
                    # API 调用后等待（频率控制）
                    anime_trace_delay = getattr(self.config, 'anime_trace_delay', 3)
                    await asyncio.sleep(anime_trace_delay)
                    
                    return {"character": "未知", "ai_detect": ai_detect, "all_results": data}
                    
        except Exception as e:
            logger.error(f"[CollectImage] 角色识别异常: {e}")
            return {"character": "未知", "ai_detect": "识别失败", "all_results": []}

    async def recognize_character_from_file(self, file_path: str) -> dict:
        """从本地文件识别角色（使用 base64 上传），图片过大时自动压缩"""
        try:
            # 从配置获取参数
            max_file_size_mb = getattr(self.config, 'max_file_size_mb', 2)
            max_dimension = getattr(self.config, 'max_image_dimension', 2000)
            jpeg_quality = getattr(self.config, 'jpeg_quality', 85)
            
            # 检查文件大小
            file_size = os.path.getsize(file_path)
            image_base64 = None
            
            if file_size > max_file_size_mb * 1024 * 1024:
                logger.info(f"[CollectImage] 图片文件过大 ({file_size/1024/1024:.2f}MB > {max_file_size_mb}MB)，进行压缩")
                with PILImage.open(file_path) as img:
                    # 获取原始尺寸
                    width, height = img.size
                    
                    # 计算缩放比例（等比例缩放）
                    if max(width, height) > max_dimension:
                        scale = max_dimension / max(width, height)
                        new_width = int(width * scale)
                        new_height = int(height * scale)
                        img = img.resize((new_width, new_height), PILImage.Resampling.LANCZOS)
                        logger.info(f"[CollectImage] 缩放图片: {width}x{height} -> {new_width}x{new_height}")
                    
                    # 转换为RGB（如果是RGBA）
                    if img.mode in ('RGBA', 'P'):
                        img = img.convert('RGB')
                    
                    # 压缩保存
                    buffer = BytesIO()
                    img.save(buffer, format='JPEG', quality=jpeg_quality, optimize=True)
                    image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                    logger.info(f"[CollectImage] 压缩后大小: {len(buffer.getvalue())/1024:.2f}KB")
            else:
                # 文件大小正常，直接读取
                with open(file_path, 'rb') as f:
                    image_base64 = base64.b64encode(f.read()).decode('utf-8')
            
            return await self.recognize_character(image_url=None, image_base64=image_base64)
        except Exception as e:
            logger.error(f"[CollectImage] 读取图片文件失败: {e}")
            return {"character": "未知", "ai_detect": "识别失败", "all_results": []}

    def _extract_characters(self, all_results: list) -> str:
        """从 AnimeTrace 结果中提取角色名和作品，返回 JSON 数组
        - not_confident=true: 取前2个
        - not_confident=false: 取第1个
        """
        if not all_results:
            return "[]"
        
        characters = []
        
        for item in all_results:
            char_list = item.get("character", [])
            if not char_list:
                continue
            
            # 根据 not_confident 决定取几个
            is_not_confident = item.get("not_confident", False)
            max_take = 2 if is_not_confident else 1
            
            for char_info in char_list[:max_take]:
                char_name = char_info.get("character", "")
                char_work = char_info.get("work", "")
                if char_name:
                    characters.append({
                        "name": char_name,
                        "work": char_work or ""
                    })
        
        if not characters:
            return "[]"
        return json.dumps(characters, ensure_ascii=False)

    @filter.command("moe")
    async def moe(self, event: AstrMessageEvent, args: str = ""):
        """搜索角色或标签的图片（模糊匹配+随机）"""
        # 解析参数: /moe <关键词> [数量]
        kw = ""
        count = 1
        
        if args:
            parts = args.strip().split()
            if parts:
                kw = parts[0]
                if len(parts) > 1:
                    try:
                        count = int(parts[1])
                    except ValueError:
                        count = 1
        
        if not kw:
            results = self.db.search_all_random_with_alias(keyword="", limit=1)
            if not results:
                yield event.plain_result("暂无图片")
                return
            for img in results:
                yield event.image_result(img["file_path"])
            return
        
        if kw == "stats":
            total = self.db.count_images()
            yield event.plain_result(f"📊 图片收集统计\n\n共收集 {total} 张图片")
            return
        
        if count < 1:
            count = 1
        if count > 10:
            count = 10
        
        # 优先搜索角色（含别名匹配）
        results = self.db.search_character_random_with_alias(keyword=kw, limit=count)
        
        # 角色没找到再搜索标签和描述（含别名匹配）
        if not results:
            results = self.db.search_all_random_with_alias(keyword=kw, limit=count)
        
        if not results:
            yield event.plain_result(f"未找到包含「{kw}」的图片")
            return

        for img in results:
            yield event.image_result(img["file_path"])

    async def terminate(self):
        if self._init_task and not self._init_task.done():
            self._init_task.cancel()
            try:
                await self._init_task
            except asyncio.CancelledError:
                pass
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        if self.web_server:
            await self.web_server.stop()
        self.db.close()
        logger.info("[CollectImage] 插件已卸载")

    async def reanalyze_image(self, image_path: str) -> dict:
        try:
            provider_id = await self._get_provider_id()
            image_url = f"file://{image_path}"

            content = await self._analyze_image_content(provider_id, image_url)
            return {
                "filter_result": "有效",
                **content
            }

        except Exception as e:
            logger.error(f"[CollectImage] 重新分析失败: {e}")
            return {
                "filter_result": "错误",
                "reason": str(e),
                "tags": {},
                "character": "",
                "description": ""
            }

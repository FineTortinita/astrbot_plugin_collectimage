import hashlib
import json
import os
import time
import shutil
from astrbot.api import AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.event.filter import EventMessageType
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.message.components import Image

from .database import Database


@register("astrbot_plugin_collectimage", "FineTortinita", "群聊图片收集插件", "v1.3.0")
class CollectImagePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.plugin_dir = os.path.dirname(__file__)
        self.images_dir = os.path.join(self.plugin_dir, "images")
        os.makedirs(self.images_dir, exist_ok=True)
        
        self.db = Database(self.plugin_dir)
        self.tags_library = self._load_tags_library()
        
        self.web_server = None
        self._init_web_server()
        
        logger.info(f"[CollectImage] 插件已加载，图片目录: {self.images_dir}")

    def _init_web_server(self):
        webui_enabled = getattr(self.config, 'webui_enabled', False)
        if webui_enabled:
            try:
                from .web_server import WebServer
                port = getattr(self.config, 'webui_port', 9192)
                self.web_server = WebServer(self, port=port)
                import asyncio
                asyncio.create_task(self.web_server.start())
            except Exception as e:
                logger.error(f"[CollectImage] 启动 WebUI 失败: {e}")

    def _load_tags_library(self) -> dict:
        tags_path = os.path.join(self.plugin_dir, "tags_library.json")
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

    def _calculate_hash(self, file_path: str) -> str:
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

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
    async def on_group_message(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        allowed_groups = self.config.get("allowed_groups", [])

        if allowed_groups and group_id not in allowed_groups:
            return

        for i, msg in enumerate(event.get_messages()):
            if isinstance(msg, Image):
                if self._is_sticker(msg, event, i):
                    logger.info("[CollectImage] 跳过表情包")
                    continue
                
                try:
                    local_path = await msg.convert_to_file_path()
                    file_hash = self._calculate_hash(local_path)
                    
                    if self.db.is_hash_exists(file_hash):
                        logger.info("[CollectImage] 图片已存在，跳过")
                        continue
                    
                    sender_id = event.get_sender_id()
                    timestamp = int(time.time())
                    ext = os.path.splitext(local_path)[1] or ".jpg"
                    image_filename = f"{timestamp}_{group_id}_{sender_id}{ext}"
                    image_path = os.path.join(self.images_dir, image_filename)
                    shutil.copy(local_path, image_path)
                    logger.info(f"[CollectImage] 图片已保存: {image_path}")

                    image_url = msg.url or msg.file
                    if image_url:
                        result = await self.analyze_image(image_url, event)
                        
                        if result.get("filter_result") != "有效":
                            logger.info(f"[CollectImage] 图片无效，跳过: {result.get('reason')}")
                            continue
                        
                        self.db.insert_image(
                            file_hash=file_hash,
                            file_path=image_path,
                            file_name=image_filename,
                            group_id=str(group_id),
                            sender_id=str(sender_id),
                            timestamp=timestamp,
                            tags=result.get("tags"),
                            character=result.get("character"),
                            description=result.get("description"),
                        )
                        logger.info(f"[CollectImage] 分析完成: {result}")

                except Exception as e:
                    logger.error(f"[CollectImage] 处理图片失败: {e}")

    async def analyze_image(self, image_url: str, event: AstrMessageEvent) -> dict:
        try:
            umo = event.unified_msg_origin
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)

            filter_prompt = """请判断这张图片是否是有效的绘画/照片素材。
有效：有人物、角色、场景、物品等具体内容的人工绘制或摄影作品。
无效：屏幕截图、表情包、大段文字、二维码、UI界面、广告图、纯文字图片、模板图等无意义内容。
请直接回答"有效"或"无效"，无需其他解释。"""

            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=filter_prompt,
                image_urls=[image_url],
            )
            filter_result = llm_resp.completion_text.strip()
            logger.info(f"[CollectImage] 筛选结果: {filter_result}")

            if "无效" in filter_result:
                return {
                    "filter_result": "无效",
                    "reason": filter_result,
                    "tags": [],
                    "character": "",
                    "description": ""
                }

            tags_prompt = self._build_tags_prompt()
            match_prompt = f"""{tags_prompt}

请分析这张图片，从上述标签中选择最匹配的标签。
要求：
1. 每个分类最多选择3个最相关的标签
2. 只选择确实存在的特征，不要猜测
3. 必须使用中文标签名返回（如"长发"、"金发"、"连衣裙"）
4. 以JSON格式返回，格式如下：
{{"gender": ["中文标签"], "hair": ["中文标签"], "clothes": ["中文标签"], "pose": ["中文标签"], "eyes": ["中文标签"], "body": ["中文标签"], "style": ["中文标签"]}}
如果某个分类没有匹配的标签，返回空列表。"""

            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=match_prompt,
                image_urls=[image_url],
            )

            try:
                import re
                json_match = re.search(r'\{[^{}]*\}', llm_resp.completion_text, re.DOTALL)
                if json_match:
                    matched_tags = json.loads(json_match.group())
                else:
                    matched_tags = {}
            except:
                matched_tags = {}

            char_prompt = """请识别这张图片中的角色名称（如果有）。
包括但不限于：动漫角色、游戏角色、原创角色等。
如果无法确定具体角色名，请回答"未知"。
只返回角色名，不要其他解释。"""

            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=char_prompt,
                image_urls=[image_url],
            )
            character = llm_resp.completion_text.strip()

            desc_prompt = "请用一句话描述这张图片的主要内容，不超过30字。"
            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=desc_prompt,
                image_urls=[image_url],
            )
            description = llm_resp.completion_text.strip()

            return {
                "filter_result": "有效",
                "reason": "",
                "tags": matched_tags,
                "character": character,
                "description": description
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

    @filter.command("search_tag")
    async def search_tag(self, event: AstrMessageEvent, tag: str, count: int = 1):
        """搜索指定标签的图片"""
        if count < 1:
            count = 1
        if count > 10:
            count = 10
        
        results = self.db.search_images(tag=tag, limit=count)
        
        for img in results:
            yield event.image_result(img["file_path"])
        
        yield event.plain_result(f"找到 {len(results)} 张包含「{tag}」标签的图片")

    @filter.command("image_stats")
    async def image_stats(self, event: AstrMessageEvent):
        """显示图片收集统计"""
        total = self.db.count_images()
        yield event.plain_result(f"📊 图片收集统计\n\n共收集 {total} 张图片")

    async def terminate(self):
        if self.web_server:
            await self.web_server.stop()
        self.db.close()
        logger.info("[CollectImage] 插件已卸载")

    async def reanalyze_image(self, image_path: str) -> dict:
        """重新分析图片（供 WebUI 调用）"""
        try:
            umo = "default"
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)

            tags_prompt = self._build_tags_prompt()
            match_prompt = f"""{tags_prompt}

请分析这张图片，从上述标签中选择最匹配的标签。
要求：
1. 每个分类最多选择3个最相关的标签
2. 只选择确实存在的特征，不要猜测
3. 必须使用中文标签名返回（如"长发"、"金发"、"连衣裙"）
4. 以JSON格式返回，格式如下：
{{"gender": ["中文标签"], "hair": ["中文标签"], "clothes": ["中文标签"], "pose": ["中文标签"], "eyes": ["中文标签"], "body": ["中文标签"], "style": ["中文标签"]}}
如果某个分类没有匹配的标签，返回空列表。"""

            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=match_prompt,
                image_urls=[f"file://{image_path}"],
            )

            try:
                import re
                json_match = re.search(r'\{[^{}]*\}', llm_resp.completion_text, re.DOTALL)
                if json_match:
                    matched_tags = json.loads(json_match.group())
                else:
                    matched_tags = {}
            except:
                matched_tags = {}

            char_prompt = """请识别这张图片中的角色名称（如果有）。
包括但不限于：动漫角色、游戏角色、原创角色等。
如果无法确定具体角色名，请回答"未知"。
只返回角色名，不要其他解释。"""

            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=char_prompt,
                image_urls=[f"file://{image_path}"],
            )
            character = llm_resp.completion_text.strip()

            desc_prompt = "请用一句话描述这张图片的主要内容，不超过30字。"
            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=desc_prompt,
                image_urls=[f"file://{image_path}"],
            )
            description = llm_resp.completion_text.strip()

            return {
                "filter_result": "有效",
                "tags": matched_tags,
                "character": character,
                "description": description
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

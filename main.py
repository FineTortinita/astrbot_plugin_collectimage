import asyncio
import base64
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from io import BytesIO
from typing import Optional

import aiohttp
from PIL import Image as PILImage
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.event.filter import EventMessageType
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.core.message.components import Image, Forward

from .database import Database


@register("astrbot_plugin_collectimage", "FineTortinita", "群聊图片收集插件", "v1.8.0")
class CollectImagePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.plugin_dir = StarTools.get_data_dir("astrbot_plugin_collectimage")
        self.images_dir = os.path.join(self.plugin_dir, "images")
        os.makedirs(self.images_dir, exist_ok=True)
        
        self.db = Database(self.plugin_dir)
        self.tags_library = self._load_tags_library()
        
        # 图片处理队列 - 串行处理所有图片
        self._image_queue = asyncio.Queue()
        self._worker_task = None
        
        self.web_server = None
        self._init_web_server()
        
        # 异步初始化
        asyncio.create_task(self._init_async())
        
        logger.info(f"[CollectImage] 插件已加载，数据目录: {self.plugin_dir}")

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
        
        if task_type == 'single':
            # 普通图片处理
            await self._do_process_single_image(task)
        elif task_type == 'forward':
            # 转发消息图片处理
            await self._do_process_forward_image(task)
        else:
            logger.warning(f"[CollectImage] 未知任务类型: {task_type}")
    
    async def _do_process_single_image(self, task):
        """处理普通图片"""
        msg = task['msg']
        event = task['event']
        group_id = task['group_id']
        sender_id = task['sender_id']
        img_index = task['img_index']
        
        if self._is_sticker(msg, event, img_index):
            logger.info("[CollectImage] 跳过表情包")
            return
        
        try:
            local_path = await msg.convert_to_file_path()
            
            if not self._check_image_size(local_path):
                logger.info("[CollectImage] 图片尺寸过小，跳过")
                return
            
            file_hash = self._calculate_hash(local_path)
            
            if self.db.is_hash_exists(file_hash):
                logger.info("[CollectImage] 图片已存在，跳过")
                return
            
            image_url = msg.url or msg.file
            
            # 先 VLM 分析，无效则不保存
            if image_url:
                result = await self.analyze_image(image_url, event)
                
                if result.get("filter_result") != "有效":
                    logger.info(f"[CollectImage] 图片无效，跳过: {result.get('reason')}")
                    return
                
                # VLM 有效后再保存图片
                timestamp = int(time.time())
                ext = os.path.splitext(local_path)[1] or ".jpg"
                image_filename = f"{timestamp}_{group_id}_{sender_id}{ext}"
                image_path = os.path.join(self.images_dir, image_filename)
                shutil.copy(local_path, image_path)
                logger.info(f"[CollectImage] 图片已保存: {image_path}")
                
                # AnimeTrace 识别
                char_result = await self.recognize_character(image_url)
                all_results = char_result.get("all_results", [])
                ai_detect = char_result.get("ai_detect", "")
                
                person_count = len(all_results)
                confirmed_count = sum(1 for r in all_results if not r.get("not_confident", False))
                not_confident_count = person_count - confirmed_count
                confirmed = 1 if confirmed_count > 0 and not_confident_count == 0 else 0
                
                character = self._extract_characters(all_results)
                # 更健壮的 ai_detect 类型检查
                ai_detect = "true" if str(ai_detect).lower() in ("true", "1", "yes") else "false"
                
                self.db.insert_image(
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
                )
                logger.info(f"[CollectImage] 分析完成: 人数={person_count}, 已确认={confirmed_count}, 未确认={not_confident_count}, 角色={character}, AI检测={ai_detect}")

        except Exception as e:
            logger.error(f"[CollectImage] 处理单图失败: {e}")

    async def _do_process_forward_image(self, task):
        """处理转发消息中的图片"""
        image_url = task['image_url']
        event = task['event']
        group_id = task['group_id']
        sender_id = task['sender_id']
        
        logger.info(f"[CollectImage] 处理转发图片: {image_url}")
        
        try:
            # 下载图片到临时位置
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as resp:
                    if resp.status != 200:
                        logger.error(f"[CollectImage] 下载图片失败: {resp.status}")
                        return
                    
                    image_data = await resp.read()
            
            # 先检查哈希（不保存）
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
                    tmp_path = tmp.name
                    tmp.write(image_data)
                
                file_hash = self._calculate_hash(tmp_path)
                
                if self.db.is_hash_exists(file_hash):
                    logger.info("[CollectImage] 转发图片已存在，跳过")
                    return
                
                if not self._check_image_size(tmp_path):
                    logger.info("[CollectImage] 转发图片尺寸过小，跳过")
                    return
                
                # VLM 分析
                result = await self.analyze_image(image_url, event)
                
                if result.get("filter_result") != "有效":
                    logger.info(f"[CollectImage] 转发图片无效，跳过: {result.get('reason')}")
                    return
                
                # VLM 有效后再保存图片
                timestamp = int(time.time())
                file_ext = ".jpg"
                image_filename = f"{timestamp}_{group_id}_{sender_id}_{uuid.uuid4().hex[:8]}{file_ext}"
                image_path = os.path.join(self.images_dir, image_filename)
                
                shutil.copy(tmp_path, image_path)
                logger.info(f"[CollectImage] 转发图片已保存: {image_path}")
                
                # AnimeTrace 识别
                char_result = await self.recognize_character(image_url)
                all_results = char_result.get("all_results", [])
                ai_detect = char_result.get("ai_detect", "")
                
                person_count = len(all_results)
                confirmed_count = sum(1 for r in all_results if not r.get("not_confident", False))
                not_confident_count = person_count - confirmed_count
                confirmed = 1 if confirmed_count > 0 and not_confident_count == 0 else 0
                
                character = self._extract_characters(all_results)
                # 更健壮的 ai_detect 类型检查
                ai_detect = "true" if str(ai_detect).lower() in ("true", "1", "yes") else "false"
                
                self.db.insert_image(
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
                )
                logger.info(f"[CollectImage] 转发图片分析完成: 人数={person_count}, 已确认={confirmed_count}, 未确认={not_confident_count}, 角色={character}, AI检测={ai_detect}")
            finally:
                # 清理临时文件
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except:
                        pass
                
        except Exception as e:
            logger.error(f"[CollectImage] 处理转发图片失败: {e}")

    async def _init_aliases_async(self):
        """异步初始化别名库"""
        alias_count = self.db.get_alias_count()
        if alias_count > 0:
            logger.info(f"[CollectImage] 数据库已有 {alias_count} 个别名，跳过导入")
            return
        
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
            logger.info(f"[CollectImage] 开始异步导入 {total} 个别名...")
            
            imported = 0
            batch_size = 100
            
            for i in range(0, len(all_aliases), batch_size):
                batch = all_aliases[i:i + batch_size]
                for alias_type, original_name, alias in batch:
                    try:
                        self.db.add_alias(alias_type, original_name, alias)
                        imported += 1
                    except:
                        pass
                
                await asyncio.sleep(0.5)
            
            logger.info(f"[CollectImage] 异步导入完成，共 {imported} 个别名")
        except Exception as e:
            logger.error(f"[CollectImage] 导入别名失败: {e}")

    def _init_web_server(self):
        webui_enabled = getattr(self.config, 'webui_enabled', False)
        if webui_enabled:
            try:
                from .web_server import WebServer
                port = getattr(self.config, 'webui_port', 9192)
                self.web_server = WebServer(self, port=port)
                asyncio.create_task(self.web_server.start())
            except Exception as e:
                logger.error(f"[CollectImage] 启动 WebUI 失败: {e}")

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

    def _calculate_hash(self, file_path: str) -> str:
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def _check_image_size(self, file_path: str, min_size: int = 300) -> bool:
        """检查图片尺寸，长或宽小于min_size返回False"""
        try:
            from PIL import Image
            with PILImage.open(file_path) as img:
                width, height = img.size
                if width < min_size or height < min_size:
                    return False
                return True
        except Exception:
            return True

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
        group_id = event.get_group_id()
        allowed_groups = self.config.get("allowed_groups", [])

        if allowed_groups and group_id not in allowed_groups:
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
        """将转发消息中的图片加入处理队列"""
        await self._image_queue.put({
            'type': 'forward',
            'image_url': image_url,
            'event': event,
            'group_id': group_id,
            'sender_id': sender_id
        })

    async def _process_single_image(self, msg: Image, event: AstrMessageEvent, group_id: str, sender_id: str, img_index: int = 0) -> None:
        """将单张图片加入处理队列"""
        await self._image_queue.put({
            'type': 'single',
            'msg': msg,
            'event': event,
            'group_id': group_id,
            'sender_id': sender_id,
            'img_index': img_index
        })

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
            matched_tags = json.loads(json_match.group()) if json_match else {}
        except:
            matched_tags = {}

        char_prompt = """请识别这张图片中的角色名称（如果有）。
包括但不限于：动漫角色、游戏角色、原创角色等。
如果无法确定具体角色名，请回答"未知"。
只返回角色名，不要其他解释。"""
        character = await self._llm_generate_with_retry(provider_id, char_prompt, [image_url])

        desc_prompt = "请用一句话描述这张图片的主要内容，不超过30字。"
        description = await self._llm_generate_with_retry(provider_id, desc_prompt, [image_url])

        return {"tags": matched_tags, "character": character, "description": description}

    async def analyze_image(self, image_url: str, event: AstrMessageEvent) -> dict:
        try:
            umo = event.unified_msg_origin
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)

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

    async def recognize_character(self, image_url: str, image_base64: str = None) -> dict:
        """调用 AnimeTrace API 识别角色，返回完整结果"""
        try:
            async with aiohttp.ClientSession() as session:
                form = aiohttp.FormData()
                
                # 优先使用 base64，其次使用 url
                if image_base64:
                    form.add_field('base64', image_base64)
                else:
                    form.add_field('url', image_url)
                
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
                        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
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
                count = int(parts[1]) if len(parts) > 1 else 1
        
        if not kw or kw == "stats":
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
        if self.web_server:
            await self.web_server.stop()
        self.db.close()
        logger.info("[CollectImage] 插件已卸载")

    async def reanalyze_image(self, image_path: str) -> dict:
        """重新分析图片（供 WebUI 调用）"""
        try:
            umo = "default"
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)
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

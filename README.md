# AstrBot 图片收集与分析插件 (astrbot_plugin_collectimage)

一款专为 AstrBot 设计的群聊图片自动化收集与结构化分析插件。通过集成视觉大模型 (VLM) 和 AnimeTrace API，插件能够自动识别群聊图片内容、提取标签和角色，并实现本地持久化存储与检索。

## 🌟 核心功能

- **自动化监听**：实时监听指定群聊中的图片消息，无需额外指令。
- **智能过滤**：
  - **元数据过滤**：精准识别并拦截 NapCat/Go-CQHTTP 等适配器发送的表情包 (Stickers)。
  - **尺寸过滤**：自动过滤小于 300px 的图片。
  - **内容过滤**：VLM 二次确认，只保留绘画/插画/CG/漫画/游戏立绘等人工绘制的图片，过滤照片。
  - **先分析后保存**：VLM 无效的图片不会保存到本地，避免垃圾文件。
- **队列处理**：串行队列处理图片，解决高频发送时的重复记录问题。
- **AnimeTrace 频率控制**：每次 API 调用间隔可配置（默认 3 秒），避免限流失败。
- **视觉模型分析**：利用 VLM 自动生成图片描述和特征标签。
- **AnimeTrace 角色识别**：
  - 自动识别动漫角色，根据检测框数量确定人数。
  - 根据 `not_confident` 标志自动标记确认状态。
  - 支持多角色图片存储。
  - 大图自动压缩（超过阈值时等比例缩放）。
- **确认状态**：
  - 全部 `not_confident=false` → 已确认
  - 有 `not_confident=true` → 未确认
  - 支持手动标记确认/未确认。
- **AI 图检测**：判断图片是否为 AI 生成。
- **结构化存储**：
  - 图片以 `时间戳_群号_发送者ID.ext` 格式保存至本地。
  - 角色信息以 JSON 数组格式存储：`[{"name": "角色名", "work": "作品名"}, ...]`
  - 支持存储多角色图片。
- **别名系统**：支持中文/日文简繁转换，通过 Bangumi 数据匹配角色/作品别名。
- **WebUI 管理界面**：现代化 UI，支持图片管理、批量操作、配置修改。
- **便捷检索**：
  - `/moe <关键词> [数量]`：搜索角色或标签的图片，随机返回。
  - `/moe stats`：显示图片收集统计。
  - 支持按角色名、作品名、标签、描述搜索。
- **合并转发支持**：支持提取合并转发消息中的图片。

## 🚀 安装方法

1. 在 AstrBot 插件目录下克隆或放入本插件文件夹：`data/plugins/astrbot_plugin_collectimage`
2. 确保环境已安装 `aiohttp` (AstrBot 通常已内置)。
3. 重启 AstrBot，插件将自动初始化数据库及存储目录。

## ⚙️ 配置说明

配置文件位于 `data/plugins/astrbot_plugin_collectimage/config.json`。

```json
{
  "allowed_groups": ["123456789"],
  "webui_enabled": false,
  "webui_port": 9192,
  "webui_password": "admin123",
  "filter_prompt": "请判断这张图片是否是有效的绘画素材...",
  "anime_trace_delay": 3,
  "max_file_size_mb": 2,
  "max_image_dimension": 2000,
  "jpeg_quality": 85,
  "thumbnail_size": 300,
  "thumbnail_cache_size": 500,
  "max_api_images": 50
}
```

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `allowed_groups` | `[""]` | **白名单模式**。仅处理此列表中的群号；若为空，则插件不处理任何群组。 |
| `webui_enabled` | `false` | 是否启用 WebUI 管理界面。 |
| `webui_port` | `9192` | WebUI 监听端口。 |
| `webui_password` | `admin123` | WebUI 访问密码，建议修改。 |
| `filter_prompt` | (见配置) | AI 图片筛选提示词，决定哪些图片被认为是有效的绘画素材。 |
| `anime_trace_delay` | `3` | AnimeTrace API 调用间隔（秒），避免频率限制。 |
| `max_file_size_mb` | `2` | 触发图片压缩的文件大小阈值（MB）。 |
| `max_image_dimension` | `2000` | 图片压缩后的最大边长（像素），等比例缩放。 |
| `jpeg_quality` | `85` | 图片压缩时的 JPEG 质量（1-100）。 |
| `thumbnail_size` | `300` | WebUI 缩略图最大边长（像素）。 |
| `thumbnail_cache_size` | `500` | 缩略图 LRU 缓存数量。 |
| `max_api_images` | `50` | API 单次返回的最大图片数量。 |

> 💡 所有配置项均可在 WebUI 的"插件配置"页面中修改。

## 🛠️ 交互指令

| 指令 | 说明 | 示例 |
| :--- | :--- | :--- |
| `/moe <关键词>` | 搜索角色或标签的图片，随机返回 1 张 | `/moe 初音` |
| `/moe <关键词> <数量>` | 搜索并返回指定数量（最多 10 张） | `/moe 初音 3` |
| `/moe stats` | 显示图片收集统计 | `/moe stats` |

**搜索说明**：
- 优先搜索角色名（含作品名）
- 角色未匹配时搜索标签和描述
- 支持搜索作品名（如 "SEKAI"）
- 支持中文/日文简繁转换搜索

## 🌐 WebUI

启用后访问 `http://<你的IP>:9192/`

功能：
- 图片列表展示（分页 + 缩略图 + 随机排序）
- 确认状态显示（✓ 已确认 / ⚠ 未确认）
- 搜索（支持别名匹配，与 /moe 命令相同逻辑）
- 查看大图和详情
- 手动编辑标签、角色、描述
- 手动标记确认/未确认状态
- 重新识别角色（AnimeTrace）
- **批量操作**：批量选择、批量确认、批量删除
- **文件导入**：从本地导入图片到数据库
- **插件配置**：在线修改所有配置参数
- **统计图表**：查看图片收集趋势
- 自动清理（删除孤立文件/数据库记录）

## 📁 目录结构

```
astrbot_plugin_collectimage/
├── main.py              # 插件主文件
├── database.py          # SQLite 数据库操作
├── web_server.py        # Web 服务器
├── web/                 # 前端静态文件
│   ├── index.html
│   ├── style.css
│   └── app.js
├── tags_library.json    # 精简 Tag 库
├── aliases.json         # 角色/作品别名数据
├── import_bangumi.py   # Bangumi 数据导入脚本
├── _conf_schema.json   # 配置定义
├── metadata.yaml       # 插件元数据
├── images/            # 图片存储目录
└── collectimage.db    # SQLite 数据库
```

## 📊 数据库字段

| 字段 | 说明 |
|------|------|
| id | 主键 |
| file_hash | MD5 哈希值（用于去重） |
| file_path | 本地文件路径 |
| file_name | 文件名 |
| group_id | 群号 |
| sender_id | 发送者 QQ |
| timestamp | 保存时间戳 |
| tags | JSON 格式标签 |
| character | 角色信息 JSON 数组：`[{"name": "角色名", "work": "作品名"}, ...]` |
| description | 图片描述 |
| ai_detect | AI 检测结果 (true/false) |
| confirmed | 确认状态 (1=已确认, 0=未确认) |
| created_at | 记录创建时间 |

## 📄 开源协议

MIT

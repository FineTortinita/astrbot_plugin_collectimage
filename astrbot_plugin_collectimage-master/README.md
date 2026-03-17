# AstrBot 图片收集与分析插件 (astrbot_plugin_collectimage)

一款专为 AstrBot 设计的群聊图片自动化收集与结构化分析插件。通过集成视觉大模型 (VLM)，插件能够自动识别群聊图片内容、提取标签，并实现本地持久化存储与检索。

## 🌟 核心功能

- **自动化监听**：实时监听指定群聊中的图片消息，无需额外指令。
- **视觉模型分析**：利用 VLM (如 GPT-4o, Gemini Pro Vision 等) 自动生成图片描述和特征标签。
- **智能过滤**：
    - **元数据过滤**：精准识别并拦截 NapCat/Go-CQHTTP 等适配器发送的表情包 (Stickers)。
    - **视觉二次确认**：若图片被 VLM 判定为表情包 (Meme)，将自动删除并终止记录。
- **结构化存储**：
    - 图片以 `时间戳_群号_发送者ID.ext` 格式保存至本地。
    - 记录存储于 SQLite 数据库，包含群组 ID、发送者、本地路径、标签及摘要。
- **便捷检索**：
    - `/search_tag <标签>`：快速检索包含特定标签的历史图片。
    - `/image_stats`：实时查看图片收集统计信息及热门标签。

## 🚀 安装方法

1. 在 AstrBot 插件目录下克隆或放入本插件文件夹：`data/plugins/astrbot_plugin_collectimage`
2. 确保环境已安装 `aiohttp` (AstrBot 通常已内置)。
3. 重启 AstrBot，插件将自动初始化数据库及存储目录。

## ⚙️ 配置说明 (`config.json`)

配置文件位于 `data/plugins/astrbot_plugin_collectimage/config.json`。

```json
{
  "allowed_groups": ["123456789"], 
  "vision_model_endpoint": "", 
  "vision_model_api_key": "",
  "enable_sticker_filter": true,
  "max_image_size_bytes": 10485760
}
```

- `allowed_groups`: **白名单模式**。仅处理此列表中的群号；若为空，则插件不处理任何群组。
- `vision_model_endpoint`: (可选) 独立视觉模型的 API 地址。若为空，则调用 AstrBot 默认模型。
- `vision_model_api_key`: (可选) 独立视觉模型的 API Key。
- `enable_sticker_filter`: 是否启用表情包过滤。
- `max_image_size_bytes`: 允许处理的最大图片大小 (默认 10MB)。

## 🛠️ 交互指令

| 指令 | 说明 | 示例 |
| :--- | :--- | :--- |
| `/search_tag <标签>` | 检索匹配标签的最近 3 张图片 | `/search_tag 猫` |
| `/image_stats` | 显示图片收集统计面板 | `/image_stats` |

## 📁 目录结构

- `images/`: 存放持久化的图片文件。
- `data.db`: SQLite 数据库文件。
- `config.json`: 插件配置文件。

## 📄 开源协议

MIT

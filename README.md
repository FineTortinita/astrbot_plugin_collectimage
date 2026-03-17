# AstrBot 图片收集与分析插件 (astrbot_plugin_collectimage)

一款专为 AstrBot 设计的群聊图片自动化收集与结构化分析插件。通过集成视觉大模型 (VLM) 和 AnimeTrace API，插件能够自动识别群聊图片内容、提取标签和角色，并实现本地持久化存储与检索。

## 🌟 核心功能

- **自动化监听**：实时监听指定群聊中的图片消息，无需额外指令。
- **视觉模型分析**：利用 VLM 自动生成图片描述和特征标签。
- **AnimeTrace 角色识别**：自动识别动漫角色，包含作品信息。
- **AI 图检测**：判断图片是否为 AI 生成。
- **智能过滤**：
  - **元数据过滤**：精准识别并拦截 NapCat/Go-CQHTTP 等适配器发送的表情包 (Stickers)。
  - **视觉二次确认**：若图片被 VLM 判定为无效图片，将自动跳过。
- **人数匹配**：根据 VLM 识别人数（如 1girl、2girls），自动从 AnimeTrace 结果中提取对应数量的角色。
- **结构化存储**：
  - 图片以 `时间戳_群号_发送者ID.ext` 格式保存至本地。
  - 记录存储于 SQLite 数据库，包含群组 ID、发送者、本地路径、标签、角色、作品、AI检测等。
- **WebUI 管理界面**：通过网页管理图片、搜索、编辑标签、重新识别。
- **便捷检索**：
  - `/moe <关键词> [数量]`：搜索角色或标签的图片，随机返回。
  - `/moe stats`：显示图片收集统计。

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
  "webui_password": "admin123"
}
```

| 配置项 | 说明 |
|--------|------|
| `allowed_groups` | **白名单模式**。仅处理此列表中的群号；若为空，则插件不处理任何群组。 |
| `webui_enabled` | 是否启用 WebUI 管理界面。 |
| `webui_port` | WebUI 监听端口，默认 9192。 |
| `webui_password` | WebUI 访问密码，默认 admin123。 |

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

## 🌐 WebUI

启用后访问 `http://<你的IP>:9192/`

功能：
- 图片列表展示（分页）
- 搜索（按标签、角色、描述）
- 查看大图和详情
- 手动编辑标签、角色、描述
- AI 重新分析（VLM）
- 识别角色（AnimeTrace）
- 删除图片

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
| character | 角色名（含作品） |
| description | 图片描述 |
| ai_detect | AI 检测结果 (true/false) |
| created_at | 记录创建时间 |

## 📄 开源协议

MIT

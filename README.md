# AstrBot 图片收集与智能归档插件 (`astrbot_plugin_collectimage`)

一款专为 [AstrBot](https://github.com/astrbotdevs/astrbot) 设计的群聊二次元插画/动漫图片自动化收集、智能筛选、角色识别与结构化归档管理插件。支持 **JEV (System One) + 视觉大模型 (VLM)** 筛选、**AnimeTrace + VLM** 双重角色识别与自动回退、**中日文简繁别名检索**，并内置高可读性的现代化 **WebUI 审片工作台**。

---

## ✨ 核心特性

### 1. 自动化收集与多级智能过滤
- **白名单群聊监听**：实时监听指定群聊中的图片与合并转发消息，无需手动触发指令。
- **表情包与小图拦截**：精准过滤 NapCat / Go-CQHTTP 等适配器发送的表情包（Stickers），并自动跳过低于最小宽高阈值（默认 `600×600px`）的图片。
- **JEV (Experiential Labs System One) + VLM 筛选**：
  - 支持接入 `jev-latest` 模型根据 `noul` 概率阈值快速判定图片是否为有效绘画素材；未配置或接口异常时自动平滑回退至 VLM 筛选。
  - 只保留动漫插画、CG、游戏立绘等有效绘画作品，过滤三次元照片、截图、二维码、聊天记录等无效图片；无效图片不落盘，避免垃圾文件堆积。
- **安全边界保护**：内置公网 IP 校验、流式下载体积上限、最大像素防解压炸弹保护及 **MD5 精确去重 + 感知哈希（dHash）近重复去重**（支持配置重复图片随机回复）。感知哈希去重可拦截重编码 / 缩放 / 二次压缩 / 加水印文字后的近似重复图片，并通过 8×8 + 16×16 双分辨率 dHash 组合避免把「版式相同、内容不同」的图片（如角色介绍卡片）误判为重复。

### 2. 角色识别与结构化标注
- **AnimeTrace + VLM 双重角色识别**：优先调用 AnimeTrace 识别动漫角色与所属作品，并根据置信度（`not_confident`）自动标记“已确认 / 待校对”状态；当未命中或接口异常时，自动回退采用 VLM 识别结果。
- **7 维特征标签与描述生成**：利用视觉大模型自动生成一句话画面描述，并从内置标签库（`tags_library.json`）提取 7 大维度标签（`gender` / `hair` / `eyes` / `clothes` / `pose` / `style` / `expression`）。
- **中日文简繁别名映射**：内置角色与作品别名数据库，支持通过中文译名、日文原名、繁体或简称双向检索。

### 3. 现代化 WebUI 审片与管理工作台
- **亮色 / 暗色双模式（Light & Dark Mode）**：柔和低反差色彩设计，支持跟随系统偏好或一键切换亮色/暗色主题，长时间审图不刺眼。
- **毛玻璃图片卡片 + 滚动动态加载（Infinite Scroll）**：每张图片卡片采用双层光学毛玻璃与插画色彩环境光晕染；向下滚动页面自动无感加载更多图片。
- **左侧图库 + 右侧常驻检片槽**：无需频繁开关弹窗，点击任意卡片即可在右侧常驻详情栏内联编辑“角色 × 作品”映射、修改画面描述、触发 VLM 重分析或按 `Space` 键一键确认归档。
- **GitHub 贡献日历热力图**：统计页采用 GitHub Contributions 风格的 7×53 周日历热力图，直观展示近 30 / 90 / 180 / 365 天的每日收录活跃度与峰值。
- **分栏分类插件配置**：右侧常驻分类目录（群聊收图与回复 / AI 视觉与筛选模型 / 压缩与缩略图缓存 / WebUI 服务与访问安全），左侧展示对应配置项，在线保存即时生效。
- **实时流水线日志**：在线查看 `[CollectImage]` 毫秒级收图、筛选与识别日志流。

---

## 🚀 安装方法

1. 进入 AstrBot 插件目录 `data/plugins/`，克隆本仓库：
   ```bash
   git clone https://github.com/FineTortinita/astrbot_plugin_collectimage.git
   ```
2. 重启 AstrBot 或在管理后台重载插件，插件会自动在 `data/plugin_data/astrbot_plugin_collectimage/` 下初始化 SQLite 数据库、图片存储目录及缩略图缓存目录。
3. 在 AstrBot 插件配置页（或配置文件 `data/config/astrbot_plugin_collectimage_config.json`）中填写 `allowed_groups` 白名单群号；如需开启 WebUI，请先设置至少 8 位的非默认密码 `webui_password` 并将 `webui_enabled` 设为 `true`。

---

## ⚙️ 配置项说明

所有配置项均可在 AstrBot 后台或插件自带的 **WebUI -> 插件配置** 页面按分类在线修改（参考 [`_conf_schema.json`](_conf_schema.json) 与 [`config.json.example`](config.json.example)）：

### 1. 群聊收图与回复
| 配置项 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `allowed_groups` | `list` | `[]` | 允许收集图片的群号白名单列表；为空时不处理任何群消息。 |
| `min_image_width` | `int` | `600` | 自动收集允许入库的最小图片宽度（像素）。 |
| `min_image_height` | `int` | `600` | 自动收集允许入库的最小图片高度（像素）。 |
| `duplicate_reply_probability` | `int` | `0` | 群聊发送已收录重复图片时的回复触发概率（`0–100`）。 |
| `duplicate_reply_messages` | `list` | `["这张图已经收录过了~", ...]` | 重复图片随机回复文案列表。 |
| `enable_phash_dedup` | `bool` | `true` | 启用感知哈希（phash）近重复去重。关闭后仅做 MD5 精确去重。 |
| `phash_threshold` | `int` | `24` | 感知哈希相似度阈值（汉明距离，`0–128`，越大越宽松）。推荐 `20–28`。 |

### 2. AI 视觉与筛选模型
| 配置项 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `enable_llm_filter` | `bool` | `true` | 启用视觉筛选（同时作为插件自动收图总开关）。 |
| `enable_llm_content` | `bool` | `true` | 启用图片内容识别（自动提取角色、7 维标签与描述）。 |
| `llm_provider_id` | `string` | `""` | 指定视觉模型 Provider ID；留空则自动使用默认可用视觉模型。 |
| `filter_prompt` | `string` | *(内置提示词)* | VLM 判断图片是否为有效绘画素材的提示词。 |
| `jev_filter_enabled` | `bool` | `false` | 启用 JEV (Experiential Labs System One) 图片有效/无效判定。 |
| `jev_filter_api_key` | `string` | `""` | Experiential Labs API Key（以 `xpl_` 开头）。 |
| `jev_filter_api_base` | `string` | `"https://api.experientiallabs.ai/v1"` | JEV API Base URL。 |
| `jev_filter_model` | `string` | `"jev-latest"` | JEV 判定使用的模型名称。 |
| `jev_filter_threshold` | `int` | `50` | JEV 有效判定阈值（百分比 `1–99`，`noul` 概率大于等于该值判为有效）。 |

### 3. 压缩与缩略图缓存
| 配置项 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `max_file_size_mb` | `int` | `2` | 触发发送前等比压缩的文件体积阈值（MB）。 |
| `max_download_size_mb` | `int` | `10` | 自动收集与 WebUI 上传允许的最大单图体积（MB）。 |
| `max_image_pixels` | `int` | `40000000` | 允许处理的最大图片像素总数（防止解压缩炸弹）。 |
| `max_image_dimension` | `int` | `2000` | 压缩后的最大边长（像素）。 |
| `jpeg_quality` | `int` | `85` | 图片压缩 JPEG 质量（`1–100`）。 |
| `thumbnail_size` | `int` | `300` | WebUI 缩略图最大边长（像素）。 |
| `thumbnail_cache_size` | `int` | `500` | 缩略图缓存数量上限。 |
| `max_api_images` | `int` | `50` | API 单次分页返回的最大图片数量。 |

### 4. WebUI 服务与访问安全
| 配置项 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `webui_enabled` | `bool` | `false` | 是否启用 WebUI 管理界面。 |
| `webui_host` | `string` | `"127.0.0.1"` | WebUI 监听地址（默认仅监听本机，配合反向代理或隧道使用）。 |
| `webui_port` | `int` | `9192` | WebUI 监听端口。 |
| `webui_password` | `string` | `""` | WebUI 登录密码（启用前必须设置至少 8 位的非默认密码）。 |
| `cors_origins` | `list` | `[]` | 允许跨域访问的 Origin 列表，留空仅允许同源请求。 |

---

## 💬 聊天交互指令

| 指令 | 说明 | 示例 |
| :--- | :--- | :--- |
| `/moe <关键词>` | 按角色名、作品名、别名、标签或描述检索图片，随机返回 1 张 | `/moe 辻仓朱比华` |
| `/moe <关键词> <数量>` | 检索并随机返回指定数量的图片（单次最多 `10` 张，支持含空格关键词） | `/moe Summer Pockets 3` |
| `/moe stats` | 查看当前图库收录总数、已确认数与今日新增统计 | `/moe stats` |
| `/moe delete`（引用图片消息） | **仅管理员**。删除被引用消息中的图片：按 MD5 精确匹配，失败时按严格阈值的感知哈希匹配；引用机器人 `/moe` 发出的消息时也会识别其中的 `#编号` | 引用图片后发送 `/moe delete` |
| `/moe delete <编号> [编号...]` | **仅管理员**。按图库编号删除图片（记录与文件），支持空格或逗号分隔，单次最多 `10` 个 | `/moe delete 12 34` |

> `/moe` 返回的每张图片后会附带 `#编号`，可直接用于 `/moe delete <编号>`，或引用该消息发送 `/moe delete`。

---

## 🧹 存量去重与维护

新收录的图片在入库前会自动做 MD5 + 感知哈希去重；存量图库中已存在的近重复图片可通过 WebUI 维护接口一次性清理（**默认 dry-run，只统计不删除**）：

```http
POST /api/maintenance/dedup
{ "dry_run": true, "threshold": 24 }   # 预览：返回近重复分组数、可清理张数与样例
{ "dry_run": false, "threshold": 24 }  # 执行：每组保留一张（优先已确认/文件存在/最早收录），删除其余图片文件与记录
```

插件启动时会为缺失或旧格式的 `phash` 自动补算，因此存量图片也能纳入去重比对。

---

## 📁 项目结构

```text
astrbot_plugin_collectimage/
├── main.py                 # 插件主入口：群消息监听、JEV/VLM 筛选、AnimeTrace 识别与指令处理
├── database.py             # SQLite 数据库操作：图片检索、简繁别名匹配与日历统计聚合
├── web_server.py           # aiohttp WebUI 后端服务：鉴权、REST API、流式上传与缩略图缓存
├── web/                    # WebUI 静态前端资源
│   ├── index.html          # 审片工作台主页面
│   ├── app.js              # 前端交互逻辑（滚动加载、常驻详情编辑、GitHub 贡献图、分类配置）
│   ├── software.css        # 亮色 / 暗色双模式样式与毛玻璃卡片视觉系统
│   └── fonts/              # 自托管字体与 SIL OFL 许可证
├── tags_library.json       # 结构化 7 维动漫特征标签库
├── _conf_schema.json       # AstrBot 插件配置 Schema 定义
├── config.json.example     # 配置文件示例
├── metadata.yaml           # AstrBot 插件元数据
└── tests/                  # 安全边界、感知哈希去重与接口单元测试
    ├── test_security.py
    └── test_phash_dedup.py
```

---

## 📄 开源协议

本项目基于 [MIT License](LICENSE) 开源。

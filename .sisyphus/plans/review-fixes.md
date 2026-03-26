# 插件审核修改计划

## 修改目标
根据 AstrBot 插件审核意见修复所有问题，确保插件符合规范。

## 修改清单

### 1. 数据持久化路径修复（严重）
**涉及文件**：main.py, web_server.py

**修改内容**：
- 引入 `from astrbot.api.star import StarTools`
- 将 `os.path.dirname(__file__)` 替换为 `StarTools.get_data_dir()`
- 确保 images 目录、数据库、配置文件、缓存目录都使用数据目录

**修改位置**：
- main.py: `__init__` 方法中的路径初始化
- web_server.py: `_get_thumbnail_cache_dir` 函数
- web_server.py: `handle_update_config` 方法

### 2. database.py search_by_tag Bug 修复
**涉及文件**：database.py

**修改内容**：
- 将 `f'%\"tag\"%'` 修改为 `f'%\"{tag}\"%'`

**修改位置**：
- database.py: `search_by_tag` 方法

### 3. 异常处理改进
**涉及文件**：database.py

**修改内容**：
- 将所有 `except: pass` 替换为带有日志记录的异常处理
- 引入 logger，记录异常信息

**修改位置**：
- database.py: `cleanup_missing_files`, `cleanup_orphaned_files` 等方法

### 4. 缩略图缓存逻辑修复
**涉及文件**：web_server.py

**修改内容**：
- 实现真正的文件缓存逻辑（而非仅内存缓存）
- 缓存文件保存到 `StarTools.get_data_dir() / cache / thumbs`
- 读取时先检查缓存文件是否存在

### 5. 文件上传流式写入
**涉及文件**：web_server.py

**修改内容**：
- 将 `file_data += chunk` 改为直接写入文件
- 使用 `while` 循环边读边写

**修改位置**：
- web_server.py: `handle_upload_image` 方法

### 6. 代码重构
**涉及文件**：main.py

**修改内容**：
- 将局部 import 移到文件顶部
- 抽取 `analyze_image` 和 `reanalyze_image` 的公共逻辑

### 7. 密码安全改进
**涉及文件**：web_server.py

**修改内容**：
- 移除 `or "admin123"` 兜底逻辑
- 如果密码为空，提示用户配置

## 执行顺序
1. 数据持久化路径修复
2. database.py Bug 修复
3. 异常处理改进
4. 缩略图缓存逻辑修复
5. 文件上传流式写入
6. 代码重构
7. 密码安全改进

## 验证方法
- 检查所有路径是否使用 StarTools.get_data_dir()
- 测试 search_by_tag 功能
- 检查异常日志输出
- 测试缩略图缓存
- 测试大文件上传
- 测试 WebUI 登录

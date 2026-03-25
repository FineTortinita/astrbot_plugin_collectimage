# 修复图片搜索随机性问题

## 问题描述
- WebUI 图片列表总是返回相同顺序的结果
- `/moe` 命令搜索时，结果数量少时总是返回同一张图片
- 原因：SQL 查询使用 `ORDER BY timestamp DESC` 固定排序

## 解决方案

### 修改 1: database.py - search_images 函数
**位置**：第 326-363 行

**修改内容**：
1. 添加 `random: bool = False` 参数
2. 根据参数选择排序方式：
   - `random=True`: `ORDER BY RANDOM()`
   - `random=False`: `ORDER BY timestamp DESC`

### 修改 2: web_server.py - handle_list_images
**位置**：第 270-290 行

**修改内容**：
- 在调用 `search_images` 时传递 `random=True`

### 修改 3: web_server.py - handle_search_images
**位置**：第 295-340 行

**修改内容**：
- 搜索接口也使用随机排序

## 验证方法
1. 访问 WebUI 图片列表，刷新页面观察是否每次显示不同图片
2. 使用 `/moe` 命令多次搜索同一关键词，验证返回结果是否随机

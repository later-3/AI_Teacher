# 阶段一开发 TODO（进度版）

> 根据 `arch.md` 的契约同步阶段一落地情况。带 ✅ 的已完成，☐ 为未完成/待加强。

## 1. 数据模型与存储
- ✅ 定义并创建 `Course / Lecture / Resource / ContentPiece / Section / Chunk` 表或模型。
- ✅ 为 `Resource` 增加 `status / retry_count / error_message / processing_stage` 字段。
- ✅ 为 `Chunk` 预留 Ready-to-Embed schema 字段（`source_ref`、`metadata` 等）。

## 2. 资源注册与状态接口
- ✅ `POST /courses`、`POST /resources`：已支持视频 URL 形式的注册。
- ✅ 自动绑定 Lecture（视频建新 Lecture，文档继承最近视频）。
- ✅ `GET /resources/{id}`：返回完整状态、processing_stage、错误信息。
- ✅ 文件上传通路：`POST /api/resources/upload` 保存文件到 storage 并自动入队。

## 3. 队列与 Worker
- ✅ 内建线程队列 + Worker，完成 `pending → queued → running → succeeded/failed` 流程。
- ✅ 支持资源入队逻辑与 `POST /resources/{id}/retry`。
- ☐ 需要调研/接入持久化队列（Redis/Celery）以支撑多实例。

## 4. 视频流水线
- ✅ 下载音频（yt-dlp）并写入 Resource.metadata。
- ✅ ffmpeg 转 wav + Faster-Whisper 输出真实时间戳。
- ✅ 将段落写入 `ContentPiece`（含 `raw_start_time`/`raw_end_time`）。

## 5. 文档流水线
- ✅ 解析 PPT（python-pptx）输出每页文本→ContentPiece（含 `page_number`）。
- ✅ 解析 PDF / 纯文本并写入 ContentPiece。

## 6. Sectioning Engine
- ✅ 按 Lecture 聚合 ContentPiece 并执行 Section 划分（时间窗口策略）。
- ✅ 统计 Section 质量（片段数、字数）并写入 metadata。
- ✅ Section 标题/摘要修改接口：`PATCH /api/sections/{id}`（合并功能待定）。

## 7. Chunk Builder & Schema 校验
- ✅ 在每个 Section 内按长度控制生成 Chunk，记录 `order_in_section`、`tokens_estimate`。
- ✅ 输出符合 Ready-to-Embed schema 的 JSON 结构。
- ✅ Schema 校验脚本：`backend/scripts/validate_chunks.py` 可校验字段、类型、长度。

## 8. 课程大纲 & Chunk 查询 API
- ✅ `GET /courses/{id}/outline`：提供 Course → Lecture → Section 树及摘要。
- ✅ `GET /courses/{id}/chunks`：分页输出所有 Chunk，供 Stage2 嵌入使用。

## 9. 可观测性与日志
- ✅ 基础 structured logging（StageTimer + log_event 输出 resource_id/stage/elapsed_ms）。
- ✅ 管理面板/简易页面展示资源状态与阶段进度尚未实现（暂可通过 API/日志查看）。

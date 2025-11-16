好，我们来把阶段二整理成一份**“开发自检用 TODO 文档”**。
你可以直接放到 `docs/task/阶段2/todo.md`，开发按这个一项一项打勾就行。

---

# 阶段二开发 TODO（进度版 / 自检用）

> 目的：根据阶段二技术方案 & 开发文档，对 Embedding Service + Vector Store + Embedding Pipeline + Search API 的落地情况进行自检。
> 说明：
>
> * ✅ 已完成
> * ☐ 未完成 / 待验证
> * ⚠ 已有初版，但需要强化 / 重构

---

## 0. 基础准备

* ✅ 环境中已安装并验证：

  * ✅ Python 依赖（transformers / qwen embedding 所需依赖）
  * ✅ Chroma 依赖（`chromadb`）
  * ✅ FastAPI + Uvicorn 正常运行
* ✅ 已复用阶段一的数据库模型（Course / Chunk 等）
* ✅ **数据库迁移**：Course 表新增 `embedding_status/embedding_progress/embedding_error` 字段并执行 migration。
* ⚠ **模型与存储目录**：`./models/qwen3-embedding-0.6b`、`./data/chroma` 已创建，但模型权重尚未下载，需要按部署环境补齐。
* ⚠ **配置项**：代码已提供默认值，但 `.env` 内尚未覆盖生产 token/路径，部署前需写入实际值。
* ✅ **Worker 重构**：队列元素改为 `WorkerTask(type="process_resource" | "embed_course", payload)`，worker loop 基于 type dispatch。

---

## 1. Embedding Service（向量服务）

> 目标：提供稳定的 `/embed` 接口，批量文本 → 向量。

### 1.1 模型加载与配置

* ✅ 在 `services/embedding/loader.py` 中：

  * ✅ 封装 `load_embedding_model()`，只在进程启动时加载一次
  * ✅ 支持 GPU 优先、无 GPU 时 fallback 到 CPU
  * ✅ 配置项通过 config（如 `EMBEDDING_MODEL_NAME/EMBEDDING_MODEL_PATH/EMBEDDING_DEVICE/EMBEDDING_MAX_TOKENS`）读取
* ⚠ 验证：尚未在下载完整模型后做实际加载测试（待模型到位）

### 1.2 向量计算核心逻辑

* ✅ 在 `services/embedding/embedder.py` 中：

  * ✅ 提供 `embed_texts(texts: List[str]) -> List[List[float]]`
  * ✅ 支持批处理（一次处理 N 条文本）
  * ✅ 对超长文本进行截断（按 token / 字符数）
  * ✅ 对空字符串做防御（返回零向量或报错）

### 1.3 `/embed` API 实现

* ✅ 在 `api/embed.py/routes.py` 中实现：

  * ✅ 路由：`POST /embed`
  * ✅ Request 模型：`{ "texts": [...], "model": "qwen3-embedding-0.6b" }`
  * ✅ Response：`{ "vectors": [[...], ...] }`
* ✅ 错误处理：

  * ✅ texts 为空时返回 400
  * ✅ 模型出错时返回 500 并记录错误日志
* ✅ 性能控制：

  * ✅ 单次请求最大文本条数（如 64 或 128）
  * ✅ 超过限制时返回友好错误或自动分批
  * ✅ 接口层校验 `X-Internal-Token`（或等价 header）以限制内部调用

### 1.4 Embedding Service 验收检查

* ✅ 手动调用 `/embed` 能得到合理维度的向量（例如 1024 维）
* ✅ 对同一文本多次调用，向量基本一致
* ✅ 对不同文本向量差异明显（粗测 cosine）
* ☐ 长文本截断逻辑被触发时有日志提醒

---

## 2. Vector Store（Chroma 向量库）

> 目标：为每门课程维护一个向量集合，支持插入与检索。

### 2.1 Chroma 初始化

* ✅ 在 `services/vectorstore.py` 中：

  * ✅ 封装 `get_chroma_client()`，单例客户端
  * ✅ 配置持久化目录（`./data/chroma`）
  * ✅ `get_course_collection()` 负责 course 级 collection 命名与创建
* ⚠ 验证：尚未在写入数据后做重启持久化测试

### 2.2 Collection 管理

* ⚠ 以 `vectorstore.get_course_collection()` 为核心实现：

  * ✅ 命名规范 `course_{course_id}` 并自动创建
  * ✅ 列出所有 collection（调试用）
  * ✅ 删除某课程的 collection（重建用）

### 2.3 向量写入（Upsert）

* ✅ `vectorstore.upsert_chunks()` 支持批量 upsert：

  * ✅ 使用 chunk_id 作为向量 id
  * ✅ metadata 包含 `course_id / lecture_id / section_id / source_type`
* ⚠ 写入失败处理：已加异常包装并记录日志，仍缺乏失败数量统计

### 2.4 向量检索（Search）

* ✅ `vectorstore.search_course_chunks()` 封装检索：

  * ✅ 支持 `section_id / lecture_id / source_type` filters
  * ✅ 返回 `{chunk_id, score, text, metadata}`

### 2.5 Vector Store 验收检查

* ✅ 某课程向量数量 ≈ Chunk 数量（课程 8/9/10 全量对齐）
* ✅ 简单问题检索能返回合理 chunk（梯度下降/损失函数示例已验证）
* ✅ filters 生效（过滤某个 section 实际减少结果）
* ☐ 清空/重建 collection 流程可用

---

## 3. Chunk Embedding Pipeline（批量向量化）

> 目标：从阶段一获取 Chunk → 生成向量 → 写入向量库 → 更新 embedding 状态。

### 3.1 拉取 Chunk（Input）

* ✅ `embedding_pipeline.run_course_embedding()` 直接使用 SQLModel 查询该课程全部 Chunk
* ⚠ 缺失文本 / schema 校验仍依赖阶段一校验结果，pipeline 内尚未做额外过滤日志

### 3.2 批量调用 `/embed`

* ✅ pipeline 内按 `embedding_batch_size` 切 batch、调用 `embed_texts`
* ✅ 失败时自动进行有限次数重试，仍需在未来完善失败明细记录

### 3.3 写入向量库

* ✅ 通过 `vectorstore.upsert_chunks` 写入 Chroma，chunk_id 与 metadata 保持一致
* ⚠ 尚无成功/失败数量统计，仅通过日志观察

### 3.4 课程级 embedding 状态

* ✅ Course 表字段已存在（stage1 migration）
* ✅ pipeline 根据批次更新 `embedding_status / progress / error`

### 3.5 `/courses/{course_id}/embed` API

* ✅ FastAPI 中实现触发接口，调用 `processor.enqueue_course_embedding`
* ✅ 处于 `pending/running` 时返回 409 防止重复

### 3.6 `/courses/{course_id}/embedding_status` API

* ✅ 接口已上线，返回 `course_id/status/progress/error`，供后台 & 自检使用

### 3.7 Embedding Pipeline 验收检查

* ✅ 对一个课程：

  * ✅ 通过脚本触发 pipeline（课程 8/9/10 实测）
  * ✅ 能看到 `embedding_status` 从 `pending → running → done`
  * ✅ Chroma 中 collection 的向量数 == chunk 数
* ☐ 错误情况：

  * ☐ 当 `/embed` 服务不可用或 Chroma 错误时，status=failed，error 字段有具体信息

---

## 4. Search API（语义检索）

> 目标：阶段三的 Teaching Engine 只用调用这个 API 获取相关知识片段。

### 4.1 `/courses/{course_id}/search` API

* ✅ Request 模型：

  ```json
  {
    "query": "什么是梯度下降？",
    "top_k": 5,
    "filters": {
      "section_id": "sec_001",
      "lecture_id": "lec_01"
    }
  }
  ```

  * ✅ query 必填，top_k 默认 5 & 最大 20
  * ✅ 需要携带 `X-Internal-Token`
  * ✅ filters 可选

* ✅ Response 模型：

  ```json
  {
    "results": [
      {
        "chunk_id": "chunk_123",
        "score": 0.87,
        "text": "梯度下降是一种一阶优化算法……",
        "metadata": {
          "lecture_id": "lec_01",
          "section_id": "sec_001",
          "source_type": "transcript"
        }
      }
    ]
  }
  ```

### 4.2 实现步骤

* ✅ 步骤 1：在路由里直接调用 `embed_texts([query])`
* ✅ 步骤 2：借助 `vectorstore.search_course_chunks` 完成检索
* ✅ 步骤 3：映射成 `SearchResponse` 返回

### 4.3 Search API 验收检查

* ✅ 对同一 query，多次调用结果稳定（顺序略微变动可接受）
* ✅ 改变 top_k，返回条数变化符合预期
* ✅ 添加 filters（如 section_id）时，结果确实被限制在对应范围
* ✅ 异常情况（课程未 embedding）时：

  * ✅ 返回 400 + `{"error":{"code":"embedding_not_ready"}}`
* ✅ Chroma 或 `/embed` 不可用时返回 503（`vector_store_error` / `embedding_service_unavailable`）

---

## 5. 日志与监控（基础版）

> 目标：出问题时开发能快速找到在哪个阶段挂了。

* ✅ Embedding Service：

  * ✅ 每次调用 `/embed` 打日志（调用来源、条数、耗时）
* ✅ Embedding Pipeline：

  * ✅ 每个批次的 embedding 和 upsert，都有 info 级别日志
  * ✅ 异常时有 error 日志 + trace
* ✅ Search API：

  * ✅ 日志包含 course_id、query、top_k、命中数量、耗时

---

## 6. 阶段二整体验收 Checklist（自检总表）

* ✅ 一门已完成阶段一的课程，触发 embedding 流程后：

  * ✅ embedding_status 从 `pending → running → done`
  * ✅ Chroma 中 collection 中的条目数 ≈ 该课程 chunk 数
* ✅ 调用 `/courses/{id}/search`，可以拿到合理相关的知识 chunk
* ✅ 对于不存在的 course_id / 未向量化课程：

  * ✅ API 返回有意义的错误提示
* ☐ 所有对外 API（embed / embed course / status / search）都有 swagger 文档或 OpenAPI 描述
* ☐ 所有模块（embedding / vector store / pipeline / search）均有基本单测或至少手工测试用例记录
* ☐ 阶段二可以在本地独立跑通（只依赖阶段一的 Chunk 数据源）

---

## 7. 后台管理（阶段二可视化 & 控制）

* ✅ 课程列表页展示 `embedding_status/embedding_progress` 以及当前向量条数（缺失向量库时显示占位符）
* ✅ 课程详情页展示详细的 embedding 状态、最新错误、向量条数
* ✅ 课程详情页提供「触发向量化」按钮，内部调用 `processor.enqueue_course_embedding`，运行中自动禁用
* ⚠ 后台暂无向量库清理/重建按钮及检索自测功能（待后续补充）

---

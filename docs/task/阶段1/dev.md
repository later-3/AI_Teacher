好，下面这份就是你要的 **「阶段一完整开发文档」**，角色定位是架构师视角：

* 我来把 **数据模型定死**、
* 把 **资源处理流程 & 小任务拆清楚**，
* 不写具体代码，让开发按这份文档落地即可。

---

# AI Teacher 项目 — 阶段一开发文档

## 阶段一：资源 → 课程结构（Ingestion + 课程建模）

---

## 0. 阶段一 Scope & 目标

### 阶段一的唯一目标

> 把用户提供的各种学习资源（视频 / PPT / PDF / 文本）
> **规范化处理 → 组织成课程结构 → 产出可向量化的文本块（带完整 metadata）**，
> 为下一阶段的「向量模型 + 向量数据库」做好输入准备。

**本阶段不做：**

* 不做 embedding（不调用 Qwen3-Embedding）
* 不做向量数据库写入
* 不做教学对话 / RAG / TTS / 前端 AI 互动

**本阶段结束时必须具备：**

1. 明确的课程数据模型：`Course / Lecture / Resource / Section / ContentPiece / Chunk`
2. 从「用户资源」到「文本片段 + 小节归属」的一条完整流水线
3. 一批 `Chunk` 数据：

   * `text`：已清洗好的文本
   * `metadata`：包含课程 / 讲次 / 小节 / 来源（时间 / 页码）等
     → 可直接送入向量模型和向量数据库

---

## 1. 整体架构位置（在整个系统中的角色）

整体系统链路（简化版）：

```text
用户资源 → [阶段一：Ingestion & 课程建模] → Ready-to-Embed Chunks
        → [阶段二：Embedding & Vector Store] → 向量库
        → [阶段三：RAG & Teaching Engine]   → 教学对话
```

阶段一主要负责这一段：

```text
[用户提供资源(URL/文件)] 
     │
     ▼
资源注册（Resource）
     │
     ▼
视频处理 / 文档处理
     │
     ▼
统一内容片段（ContentPiece）
     │
     ▼
小节划分（Sectioning）
     │
     ▼
课程结构（Course / Lecture / Section）
     │
     ▼
可向量化文本块（Chunk，Ready-to-Embed）
```

---

## 2. 数据模型设计（最终结构）

> 这是本阶段的“地基”。后面所有模块都围绕这些实体传递和处理数据。

### 2.1 实体总览

我们需要以下核心实体：

1. `Course`：课程（整门课）
2. `Lecture`：讲次 / 章节（可选一层，用来承接多节视频）
3. `Resource`：原始资源（视频 / PPT / PDF / 文本）
4. `ContentPiece`：统一内容片段（从视频转录、PPT、PDF 分解来的“最小文本单位”）
5. `Section`：知识小节（教学颗粒度单位）
6. `Chunk`：最终可向量化的文本块（Section 内整合后的文本片段）

---

### 2.2 各实体字段定义（逻辑层面）

> 类型不写死，开发可以用 ORM（SQLAlchemy 等）自行落地。这里是“字段语义 + 关系”。

#### 2.2.1 Course（课程）

* `id`: 唯一标识（int/uuid）
* `name`: 课程名称（如「MIT 线性代数导论」）
* `description`: 简要描述（用户填 + 后续可用 LLM 生成补充）
* `created_by`: 创建人（用户 id，先可选）
* `created_at`: 创建时间
* `updated_at`: 更新时间
* `metadata`: JSON，预留（标签、来源平台等）

> 关系：
>
> * 1 个 Course 有多个 Lecture
> * 1 个 Course 有多个 Resource
> * 1 个 Course 有多个 Section/Chunk（通过 Lecture 关联）

---

#### 2.2.2 Lecture（讲次 / 章节）

* `id`
* `course_id`（FK → Course）
* `title`: 讲次标题（如「第 1 讲：绪论」）
* `order_index`: 顺序（第几讲）
* `description`: 讲次说明（可选）
* `metadata`: JSON（可选：来源视频列表、时长等）

> 关系：
>
> * 1 个 Lecture 对应 1~N 个 Resource（通常是视频）
> * 1 个 Lecture 有多个 Section

---

#### 2.2.3 Resource（原始资源）

* `id`
* `course_id`（FK → Course）
* `lecture_id`（FK → Lecture，可为空，之后分配）
* `type`: 枚举：`video / ppt / pdf / text / other`
* `source_url`: 原始 URL（B 站 / YouTube 等，文件上传则为空）
* `original_filename`: 源文件名（PPT/PDF/Text）
* `status`: 枚举：

  * `pending`
  * `downloading`
  * `processing`
  * `ready`
  * `failed`
* `error_message`: 处理失败时的错误信息（可空）
* `metadata`: JSON：

  * 对于 video：时长、分辨率、平台信息等
  * 对于文档：页数等
* `created_at`
* `updated_at`

> 关系：
>
> * Resource 是所有 raw 数据的入口
> * 一个 Resource 可以产生多个 ContentPiece

---

#### 2.2.4 ContentPiece（统一内容片段：最小内容单位）

这是阶段一的核心中间层，用来统一所有“被解析出来的文本”。

* `id`
* `course_id`（冗余存储，方便查询）
* `lecture_id`（可空，之后关联）
* `resource_id`（FK → Resource）
* `section_id`（FK → Section，可为空，Sectioning 完成后填）
* `source_type`: 枚举：

  * `transcript`（视频转录）
  * `slide`（PPT）
  * `pdf`
  * `note`（用户文本等）
* `text`: 该片段的纯文本内容
* `language`: 语言标识，例如 `zh` / `en` / `mixed`（可由 simple 检测或 LLM 判定）
* `raw_start_time`: 对于 transcript：起始时间（秒），否则为空
* `raw_end_time`: 对于 transcript：结束时间（秒），否则为空
* `page_number`: 对于 PPT/PDF：页码，否则为空
* `order_in_resource`: 此片段在该 Resource 中的顺序索引
* `metadata`: JSON：

  * 可放：原始 ASR 置信度、文本类别（定义/例子）、结构标签等

> 关系：
>
> * ContentPiece 是“后续所有 Section 和 Chunk 的原材料”
> * 由视频/文档处理流水线生成

---

#### 2.2.5 Section（知识小节）

Section 是教学的基本单元，也是后面 RAG / Teaching Engine 的关键粒度。

* `id`
* `course_id`（FK → Course）
* `lecture_id`（FK → Lecture）
* `title`: 小节标题，例如「损失函数的直观理解」
* `summary`: 小节简要说明（用于课程大纲展示，与教学引擎提示）
* `order_in_lecture`: 在该 Lecture 中的顺序
* `approx_start_time`: 该小节大致起始时间（秒，视频向量约位，选填）
* `approx_end_time`: 该小节大致结束时间
* `metadata`: JSON：

  * 关联的资源列表（resource_ids）
  * 以哪些规则被划分出来（便于调试）

> 关系：
>
> * 一个 Section 关联多个 ContentPiece（通过 section_id）
> * 一个 Section 之后会产出多个 Chunk

---

#### 2.2.6 Chunk（Ready-to-Embed 文本块）

Chunk 是最终要被向量化的单位，通常比 ContentPiece 略大，
是按 Section 内的语义 / 长度 做过合并/切分后的结果。

* `id`
* `course_id`
* `lecture_id`
* `section_id`
* `text`: 要喂给 embedding 模型的完整文本（长度控制在合理区间）
* `source_piece_ids`: 列表（关联的 ContentPiece.id 集合）
* `language`
* `metadata`: JSON：

  * `source_types`（包含 transcript/slide 等）
  * `time_ranges`（若来自多个片段，可存一个数组）
  * `page_numbers`（涉及的页码列表）
  * 将来可以放标签（定义/例子/公式）

> ⚠️ 注意：
> 阶段一只负责生成 Chunk（内容+metadata），不计算 embedding。
> 阶段二才会在 Chunk 上添加 embedding，并写到向量库。

---

## 3. 阶段一功能模块 & 流程（架构视角）

### 3.1 阶段一模块划分

1. **资源注册模块（Resource Registry）**
2. **视频处理流水线（Video Pipeline）**
3. **文档处理流水线（Doc Pipeline）**
4. **内容统一模块（ContentPiece Builder）**
5. **小节划分模块（Sectioning Engine）**
6. **课程结构构建模块（Course Structure Builder）**
7. **Chunk 生成模块（Chunk Builder / Ready-to-Embed）**
8. **状态查询 & 课程大纲 API**

下面逐个说明「做什么」+「顺序 & 依赖」。

---

## 4. 各模块说明 & 开发任务（不含代码）

### 4.1 资源注册模块（Resource Registry）

**目标：**
所有资源（URL / 文件）有统一入口、统一状态管理，后续处理围绕 Resource.id 进行。

**主要职责：**

1. 提供接口创建 Course（课程）
2. 提供接口向课程中添加 Resource：

   * 输入：course_id + 资源类型 + URL / 上传文件
   * 创建 Resource 记录，状态设为 `pending`
3. 简单的 Resource 状态查看接口：

   * 根据 course_id / resource_id 查询处理状态

**开发任务：**

* 设计 Resource/Course 的创建接口（REST / RPC 皆可，推荐 REST）
* 将上传的文件保存到统一的文件目录（如 `/data/raw/...`），写入 metadata
* 状态字段的更新规范（后续流水线要按状态变更）

---

### 4.2 视频处理流水线（Video Pipeline）

**目标：**
从 Resource（type=video） → 音频 → 带时间戳的转录文本 → ContentPiece（source_type=transcript）。

**主要步骤：**

1. **视频元数据拉取（可选）**

   * 使用 yt-dlp 获取标题、时长，大致视为 Lecture 标题候选
2. **音频抽取**

   * 使用 yt-dlp 下载音频
   * 存储路径记录到 Resource.metadata 或专门字段（如 `audio_path`）
   * Resource 状态：`downloading → processing`
3. **ASR 转录**

   * 使用 Faster-Whisper 对音频进行转写
   * 输出 segments：`(start, end, text)`
4. **转录转换为 ContentPiece**

   * 遍历 segments，生成多条 ContentPiece：

     * `source_type = transcript`
     * 填 `course_id、resource_id、raw_start_time、raw_end_time、text、order_in_resource`
   * `section_id` 暂时为空，等 Sectioning 填

**开发任务：**

* 视频流水线执行器：

  * 输入：resource_id（type=video）
  * 执行上述 2–4 步，并更新 Resource.status 为 `ready` 或 `failed`
* 处理错误和重试策略（如下载失败、ASR 异常）

---

### 4.3 文档处理流水线（Doc Pipeline）

**目标：**
从 Resource（type=ppt/pdf/text） → 页级/段落级文本 → ContentPiece（source_type=slide/pdf/text）。

**主要步骤：**

1. **PPT 解析**

   * 对每页读取文本：

     * 标题、内容等
   * 为每页生成一个或多个 ContentPiece：

     * `source_type=slide`
     * `page_number` 写入
     * `order_in_resource` 对应页序或页内序

2. **PDF 解析**

   * 按页提取文本
   * 可按段落拆分 or 整页一块
   * 生成 ContentPiece（source_type=pdf）

3. **纯文本解析**

   * 按行/段落拆分
   * 生成 ContentPiece（source_type=text）

**开发任务：**

* 同样有一个文档流水线执行器：

  * 输入：resource_id（type in ppt/pdf/text）
  * 对应解析存成 ContentPiece
  * 更新 Resource.status 为 `ready` / `failed`

---

### 4.4 内容统一模块（ContentPiece Builder）

> 视频 & 文档流水线已经生成 ContentPiece，本模块更多是抽象层：
> 确保所有 ContentPiece 结构统一、可查询。

**主要职责：**

* 保证所有 ContentPiece 都有：

  * 正确的 `course_id / resource_id / source_type / text / raw_position / order_in_resource`
* 提供查询接口：

  * 按 course_id 查询所有 ContentPiece
  * 按 resource_id 查询某个资源的 ContentPiece 列表

**开发任务：**

* 如果使用 ORM，这部分更多是模型 + 简单查询
* 可以视为“非独立模块”，是流水线产出的公共结果层

---

### 4.5 小节划分模块（Sectioning Engine）

**目标：**
将 ContentPiece 按课程维度聚合成 Section（知识小节），建立 Section & ContentPiece 的关联。

**MVP 策略（先简单，后优化）：**

1. **视频驱动的小节划分**

   * 对每个视频资源（或 Lecture）：

     * 按时长平均切 N 段（例如每 3–5 分钟一个 Section）
     * 找出 start_time 落在该段内的所有 transcript ContentPiece
     * 这些片段组成一个 Section 的“语料”

2. **PPT 辅助划分（增强可选）**

   * 简单版本：每页 PPT 对应一个 Section
   * 或：在视频 Section 内附加与时间上接近的 PPT 页（后做）

**Section 属性生成：**

* `lecture_id`：可以直接让每个视频映射成一个 Lecture
* `order_in_lecture`：按时间排序
* `title`：

  * MVP 可先自动拼接：“Lecture 1 - Section 3”
  * 如要更好体验，可在后续加一个 LLM 步骤生成更有语义的标题
* `summary`：

  * 可以先为空，后面一个阶段统一调用 LLM 写 summary

**开发任务：**

* Sectioning 执行器：

  * 输入：course_id
  * 获取该课程下所有 Resource / ContentPiece
  * 按策略生成：多个 Section 记录
  * 关联 Section 和 ContentPiece（填 `section_id` 字段）

* 简单调试接口：

  * 查询某课程的 Section 列表
  * 查询某 Section 下的 ContentPiece（看效果）

---

### 4.6 课程结构构建模块（Course Structure Builder）

**目标：**
把 Course / Lecture / Section 构成一棵可展示的大纲树。

**主要职责：**

1. **Lecture 创建策略**

   * 简单版：

     * 每个视频 Resource 对应一个 Lecture
     * Lecture.title 优先用 Resource 元数据中的标题

2. **Section 排序与挂载**

   * 按 `lecture_id + order_in_lecture` 排序
   * 将 Section 排到对应 Lecture 下

3. **课程大纲接口**

* 接口返回结构（示意）：

```json
{
  "course_id": 1,
  "name": "机器学习导论",
  "lectures": [
    {
      "lecture_id": 10,
      "title": "第 1 讲：绪论与线性回归",
      "sections": [
        {
          "section_id": 101,
          "title": "什么是机器学习",
          "summary": "……",
          "order_in_lecture": 1
        },
        ...
      ]
    }
  ]
}
```

**开发任务：**

* Lecture 的自动创建与更新逻辑
* 课程大纲查询接口：`GET /courses/{course_id}/outline`
* 确认前端/后续 Teaching Engine 只依赖这一个大纲接口就能知道“讲什么”

---

### 4.7 Chunk 生成模块（Chunk Builder / Ready-to-Embed）

**目标：**
在 Section 内把 ContentPiece 合理拼成 Chunk，让 embedding 模型有良好的输入粒度。

**主要职责：**

1. **Chunk 粒度策略**

   * 目标长度：比如 200–500 字一块（或按 token 粗估计）
   * 在同一 Section 内按照 `order_in_resource` 顺序遍历 ContentPiece：

     * 依次累积 text，直到接近上限就切一块
     * 保持不跨 Section

2. **Chunk 内容与 metadata 构建**

   * `text`：组合后的内容（中间可加换行）
   * `source_piece_ids`：参与该 Chunk 的 ContentPiece.id 列表
   * `metadata`：

     * 混合 source_type（transcript/slide 等）
     * time_range（最小 start_time 到最大 end_time）
     * page_numbers（涉及页码集合）

3. **接口：列出所有 Chunk**

   * 按 `course_id` 或 `section_id` 查询 Chunk 列表
   * 提供给下一个阶段的 embedding pipeline

**开发任务：**

* Chunk 生成执行器：

  * 输入：course_id
  * 获取该课程所有 Section 和 ContentPiece
  * 按策略生成一批 Chunk
* Chunk 查询接口：为后续 embedding 阶段提供统一入口

---

### 4.8 状态查询 & 可观测性

**目标：**
让开发/运维/你自己能看清楚某门课/某个资源当前进行到哪一步。

**建议提供：**

1. **课程级状态接口**

   * 包含：

     * Course 基本信息
     * 所有 Resource 的状态
     * Section / Chunk 是否已生成

2. **资源级详情接口**

   * 某一个 Resource 的：

     * 状态
     * 错误信息
     * 产生的 ContentPiece 数量

3. **简单日志规范**

   * 每个阶段（视频下载、ASR、PPT解析、Sectioning、Chunking）有清晰日志前缀，便于排查问题

---

## 5. 阶段一开发计划（架构视角的顺序建议）

> 这里不写时间估算，只给“推荐顺序 + 依赖关系”。

### 步骤 1：数据模型与存储确定

* 实体：Course / Lecture / Resource / ContentPiece / Section / Chunk
* 关系：ER 图画清楚
* 在数据库/ORM 中建表

### 步骤 2：资源注册模块（可以最先做）

* 实现 Course 创建接口
* 实现 Resource 创建接口（支持 video + 文件上传）
* 实现 Resource 状态查询接口

### 步骤 3：视频处理流水线

* 能从 Resource（video）→ 音频文件
* 能做 ASR → 得到转录 segments
* 能把 segments 写成 ContentPiece（source_type=transcript）

### 步骤 4：文档处理流水线

* 对 PPT/PDF/Text 资源解析
* 生成 ContentPiece（source_type=slide/pdf/text）

### 步骤 5：Sectioning & 课程结构构建

* Sectioning 执行：

  * 按 course_id 聚合 ContentPiece
  * 用规则创建 Section
  * 关联 ContentPiece.section_id
* Lecture 自动创建逻辑（先简单映射一讲一个视频）
* 课程大纲查询接口

### 步骤 6：Chunk 生成

* 实现 Chunk 生成逻辑：

  * Section 内合并 ContentPiece 成 Chunk
* 提供 Chunk 查询接口（按 course / section）

### 步骤 7：内部联调 & 测试

* 典型流程：

  1. 创建 Course
  2. 注册一个 B 站/YouTube 视频 + 一个 PPT
  3. 触发阶段一处理
  4. 最终能看到：

     * 课程大纲（Lecture + Section）
     * 每个 Section 下的 Chunk 列表（可读的文本）

---

## 6. 阶段一完成的验收标准（从架构角度）

当满足以下条件时，可以认为阶段一从架构和实现上“过关”：

1. **给一个新课程 + 视频/PPT 资源，整个流水线能跑完**：

   * 所有 Resource 状态为 `ready`
   * 生成 ContentPiece、Section、Chunk

2. **有课程大纲接口**：

   * 明确列出 Lecture & Section （标题至少有基础可读性）

3. **有 Chunk 列表接口**：

   * 对给定 course_id 能拿到所有 Chunk
   * 每个 Chunk 都带清晰 metadata（course/lecture/section/source/time/page）

4. **后续团队可以在完全不关心资源细节的情况下，直接用 Chunk 做 embedding**：

   * 嵌入工程师只需要：

     * 调 `GET /courses/{id}/chunks`
     * 取 `chunk.text` 做 embedding
     * 把 embedding + chunk.metadata 写入向量库
   * 不需要理解视频/PPT 怎么来的

---

这份文档你可以直接当做：

* ✅ 阶段一的架构设计说明
* ✅ 团队对齐「数据模型 + 模块划分 + 流程顺序」的基准

如果你愿意，下一步我可以帮你写一份 **「面向开发的 API 设计文档（只包含接口和请求/响应结构，不含实现）」**，主要针对：

* 资源注册接口
* 课程大纲接口
* Chunk 查询接口

你可以把它当成「后端接口规范 v1」，给前端和后续 embedding/RAG 使用。

步骤 1：在 WSL 里安装 Node（推荐用 nvm）

在 WSL 终端（Ubuntu）里执行：

```bash
# 安装 nvm（Node 版本管理工具）
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
```

安装完后，重新打开一个 WSL 终端（或者手动执行下面这行）：
```bash
source ~/.nvm/nvm.sh
```
然后安装 Node：
```bash
nvm install --lts
nvm use --lts
```
验证：

```bash
which node
which npm
node -v
npm -v
```

---

## Step 1：在 WSL 里创建项目和虚拟环境

在 WSL 里：

```bash
cd ~/code   # 或你自己的工作目录
mkdir -p AI_Teacher
cd AI_Teacher

python3 -m venv venv
source venv/bin/activate
```

以后每次开发前都先：

```bash
cd ~/code/AI_Teacher
source venv/bin/activate
```

---

2. 安装系统级工具（ffmpeg 等）

这些用 apt 安装一次就好：
```bash
sudo apt update
sudo apt install -y \
  git \
  curl \
  wget \
  ffmpeg \
  build-essential
```

ffmpeg 用于 Whisper 处理音频

build-essential 用于编译某些 Python 依赖

安装 CUDA 版（官方 cu121 源）：
```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121  --proxy http://127.0.0.1:7897
```

安装完成后测试：
```bash
python - << 'EOF'
import torch
print("torch version:", torch.__version__)
print("cuda available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("cuda device:", torch.cuda.get_device_name(0))
EOF
```

期望输出：
- cuda available: True
- cuda device: NVIDIA GeForce RTX 4070 ...

## Step 2：安装 Python 依赖（embedding_service 需要的）

先装最小必要包：

```bash
pip install --upgrade pip

pip install \
  fastapi \
  "uvicorn[standard]" \
  "transformers>=4.40.0" \
  pydantic \
  chromadb \
  langchain \
  openai \
  tiktoken \
  yt-dlp \
  faster-whisper
```

说明：

- fastapi + uvicorn：后端 / embedding 服务 API
- transformers：加载 Qwen 等模型
- chromadb：向量数据库（MVP 用 Chroma）
- langchain：后续 RAG & 教学逻辑
- yt-dlp：下载 B 站 / YouTube 视频音频
- faster-whisper：ASR（语音转文字）
后续如果发现缺什么库再加，这些是 MVP 必备的。

---

## Step 3：创建 embedding_service 目录和代码

在项目里：

```bash
mkdir -p embedding_service
cd embedding_service
```

新建 `app.py`（你可以用 `code app.py` 用 VSCode 打开，或者用 `nano app.py`）：

```python
# embedding_service/app.py

from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
import torch
from transformers import AutoTokenizer, AutoModel

MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"

app = FastAPI(title="Qwen3 Embedding Service")

print("⏳ Loading tokenizer and model...")

tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModel.from_pretrained(MODEL_NAME)
model.eval()

# 如果有 GPU，后面可以改成 .to("cuda")
device = torch.device("cpu")
model.to(device)

print("✅ Model loaded.")


class EmbedRequest(BaseModel):
    texts: List[str]


class EmbedResponse(BaseModel):
    vectors: List[List[float]]


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    简单的 mean pooling，把序列 token 向量平均成一句话向量
    """
    inputs = tokenizer(
        texts,
        padding=True,
        truncation=True,
        return_tensors="pt",
        max_length=512,
    ).to(device)

    with torch.no_grad():
        outputs = model(**inputs)
        # outputs.last_hidden_state: [batch, seq_len, hidden]
        last_hidden = outputs.last_hidden_state
        # 按 seq_len 维度做平均
        embeddings = last_hidden.mean(dim=1)  # [batch, hidden]

    # 转成 Python list，方便通过 JSON 返回
    return embeddings.cpu().tolist()


@app.post("/embed", response_model=EmbedResponse)
def embed(req: EmbedRequest):
    vectors = embed_texts(req.texts)
    return EmbedResponse(vectors=vectors)


@app.get("/health")
def health():
    return {"status": "ok"}
```

> 这就是你的 **「本地向量模型服务器」** 了：
>
> * POST `/embed` → 输入一组文本，返回一组向量
> * GET `/health` → 健康检查

---

## Step 4：运行 embedding_service

在 `AI_Teacher` 根目录（确保 venv 激活）：

```bash
cd ~/code/AI_Teacher
source venv/bin/activate

uvicorn embedding_service.app:app --host 0.0.0.0 --port 8001
```

第一次跑会下载模型，时间会久一点，这是正常的。
等终端出现类似：

```text
INFO:     Uvicorn running on http://0.0.0.0:8001
```

就说明服务启动成功了。

---

## Step 5：本地测试一下 /embed 接口

另开一个 WSL 终端（或者在 VSCode 里开一个新 terminal），同样激活 venv（虽然这一步其实不强制，但习惯好点）：

```bash
cd ~/code/AI_Teacher
source venv/bin/activate
```

用 `curl` 测一下：

```bash
curl -X POST "http://localhost:8001/embed" \
  -H "Content-Type: application/json" \
  -d '{"texts": ["你好，老师", "I want to learn linear regression"]}'
```

你应该会看到类似结构的返回（很长）：

```json
{"vectors": [[0.01, -0.03, ...], [...]]}
```

说明：

* 模型加载成功
* FastAPI 正常
* 你的本地向量服务已经 ready ✅

---

## Step 6：后端 / LangChain 以后怎么用它？

等我们下一步做 RAG / Teaching Engine 的时候，就可以在 Python 里像这样用：

```python
import requests

def embed_with_qwen(texts):
    resp = requests.post(
        "http://localhost:8001/embed",
        json={"texts": texts},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["vectors"]
```

并且可以封装成一个 LangChain 的自定义 Embeddings 类，后面再做。

---

## 接下来可以干什么？

我们已经完成了 **MVP 的关键底座之一：本地向量模型服务**。
下一步有几条路线可以选：

1. **路线 A：开始搭「向量知识库 + RAG」**

   * 建一个脚本：

     * 调用 yt-dlp 下载音频
     * 调用 Whisper 做 ASR
     * 切 chunk
     * 调 `/embed` 得到向量
     * 写入 Chroma 向量库

2. **路线 B：先做一个最小的后端 `/ask` 接口**

   * 给一个问题
   * 调用 embedding + 向量库 + LLM
   * 返回一个简单回答（尚不涉及教学流程）

3. **路线 C：先做前端 Demo**

   * 用你 npm 安装的东西（比如 codex 帮你 scaffold）
   * 做一个简单 chat UI，后端暂时只回固定文本

按你现在节奏，我会建议走 **路线 A**：

> 把“课程 → 文本 → 向量 → 向量库”这条链路先打通，AI Teacher 才有东西可讲。

如果你愿意，我们下一步就可以：

* 直接写一个 **「ingest_lecture.py」脚本骨架**：

  * 传入 B 站 / YouTube URL + PPT 路径
  * 自动：下载 → ASR → 切片 → 调 /embed → 存到 Chroma

你要的话我就直接给你这份脚本的详细版本。



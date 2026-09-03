# 部署说明（后端）

赛题：XH-202630 领域知识个性化生成与多智能体协同决策系统
组件：FastAPI 多智能体后端（`backend/`）

> 本说明每一步均对应仓库真实文件，可直接照做。
> 字段名、路径、端口均以代码为准。

---

## 1. 环境要求

| 项 | 要求 | 依据 |
|---|---|---|
| **Python** | **3.13（硬性）** | `Dockerfile:5` `FROM python:3.13-slim` |
| 依赖 | `pip install -r requirements.txt`（已锁版本） | `requirements.txt` |
| 配置 | 需要 `.env`（含 LLM API Key） | 模板 `.env.example` |

⚠️ **不可用 Python 3.10**：缺少 `FlagEmbedding` 会导致知识库降级为 Stub，
检索失效、指标失真。

---

## 2. ⚠️ OpenMP 段错误 Workaround（必设）

`bge-m3` / `FlagEmbedding` 在多线程 OpenMP 下偶发 torch 段错误（SIGSEGV），
与版本无关（OpenMP 竞态）。**根治方法：强制单线程**。

```bash
export OMP_NUM_THREADS=1     # Windows: set OMP_NUM_THREADS=1
```

- 本地：启动服务前执行
- Docker：`Dockerfile:10` 已内置 `ENV OMP_NUM_THREADS=1`，无需额外设置
- Windows：项目 `.venv` 已附带 `sitecustomize.py` 自动设置，用 `.venv/Scripts/python.exe` 即可

---

## 3. 配置 API Key（关键）

```bash
cp .env.example .env
```

编辑 `.env`，**只需填这两个字段**（其余均有默认值，无需改动）：

```bash
DEEPSEEK_API_KEY=sk-xxx    # DeepSeek 平台申请（中档模型 deepseek-chat）
OPENAI_API_KEY=sk-xxx      # 阿里云 DashScope 申请（qwen-max / qwen-turbo，走 DashScope 的 OpenAI 兼容端点）
```

> ⚠️ **注意**：配置中**没有** `LLM_API_KEY` / `LLM_BASE_URL` 这类字段。
> 字段名以 `.env.example` 为准（对应 `config.py` 的 `deepseek_api_key` / `openai_api_key`）。
> 填错字段名会导致 Key 读不到、LLM 调用失败。

---

## 4. 大体积资产（提交包已含，解压即用）

> **赛题提交方式（八、(二)）**：作品统一打包提交，过大则上传云盘。
> 因此本项目的**提交包为自包含**——`data/bge_m3_model/`（嵌入模型，约 2.27GB）
> 与 `data/numpy_kb/`（预计算向量库）**已随包提供**，评委**解压后无需任何外网**即可运行。
> 本节仅说明资产构成，以及「自行重新获取」的兜底方式。

### 4.1 bge-m3 嵌入模型（约 2.27GB）

提交包内已含 `data/bge_m3_model/`（BAAI/bge-m3）。无需下载。
兜底（仅当包内缺失时）：

```bash
# 方式 A（推荐）
python scripts/fetch_assets.py --model-only

# 方式 B：手动
git clone https://hf-mirror.com/BAAI/bge-m3 data/bge_m3_model
```

### 4.2 预计算向量库 numpy_kb（分卷已在仓库，提交包内已合并）

`vectors.npy`（133MB）超过 GitHub 单文件 100MB 限制，Git 仓库中以
`vectors.npy.part0` / `.part1` 分卷提交；**提交包内已合并为完整 `vectors.npy`**。
启动器 `scripts/start_server.py` 会在启动时自动检测并合并分卷（如仅有分卷）。

手动合并（仅在仅有分卷时）：

```bash
# Linux / macOS / Git Bash
cat data/numpy_kb/vectors.npy.part* > data/numpy_kb/vectors.npy

# Windows CMD
copy /b data\numpy_kb\vectors.npy.part0 + data\numpy_kb\vectors.npy.part1 data\numpy_kb\vectors.npy

# Windows PowerShell
Get-Content data\numpy_kb\vectors.npy.part0, data\numpy_kb\vectors.npy.part1 -Raw -AsByteStream |
    Set-Content data\numpy_kb\vectors.npy -NoNewline -AsByteStream
```

> 组装自包含提交包见 `scripts/assemble_submission.py`；一键启动见第 5 节。

---

## 5. 启动

### 方式 A（推荐）：一键启动器

启动器会自动设置 `OMP_NUM_THREADS=1`（避免 bge-m3 段错误）、
自动合并知识库分卷、预检模型与 Key，再拉起服务：

```bash
python scripts/start_server.py                 # 默认 0.0.0.0:8000
python scripts/start_server.py --port 8080      # 自定义端口
```

### 方式 B：手动启动

```bash
export OMP_NUM_THREADS=1     # Windows: set OMP_NUM_THREADS=1
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### 方式 C：Docker

```bash
docker build -t wolegedou-backend .

docker run -d --name wolegedou \
  --env-file .env \
  -p 8000:8000 \
  wolegedou-backend
```

Docker 说明：
- `docker-entrypoint.sh` 会**自动合并分卷**，并在 `data/bge_m3_model/` 缺失时尝试拉取
- `.env` **不进镜像**，用 `--env-file` 注入
- 若无外网，请预先把 `data/bge_m3_model` 放入 `data/`，或挂载：`-v "$(pwd)/data:/app/data"`
- 端口默认 8000，可用 `PORT` 环境变量覆盖

---

## 6. 验证

### 6.1 启动日志（看到这些行即表示启动成功）

启动后控制台会**依次输出**以下关键行，请确认：

```
正在初始化数据库...
数据库已就绪: <项目根>/data/wolegedou.db
正在初始化知识库...
[NumpyKB] 加载完成: 30532 chunks, dim=1024
[知识库] 初始化成功 (Numpy 模式), 当前 chunk 数: 30532
多智能体协同决策系统启动完成
Uvicorn running on http://0.0.0.0:8000
```

> ⚠️ 若看到 `[知识库] Numpy 后端初始化失败`、`FlagEmbedding 加载失败`，
> 或 chunk 数远小于 30532，说明知识库未正确加载
> （通常是第 4 节分卷未合并或 bge-m3 模型缺失），请补齐资产后重启。

> ℹ️ **关于 "Embedding 模型加载成功"**：该行出现在**首次 RAG 查询**时（模型懒加载），
> 不在 uvicorn 启动阶段。启动后先调一次 `/api/ask` 或 `/api/kb/search`，
> 控制台才会打印 `Embedding 模型加载成功 (后端: FlagEmbedding)`。

### 6.2 接口验证

```bash
# 1) 健康检查
curl http://localhost:8000/health
# 预期：{"status":"ok"}

# 2) 知识库健康检查
curl http://localhost:8000/api/kb/health
# 预期（冷启动、尚未发生任何查询时）：
#   {"mode":"numpy","chunk_count":30532,"embedding_backend":null,"local_model_ready":true,...}
# 预期（首次查询后，模型完成懒加载）：
#   {"mode":"numpy","chunk_count":30532,"embedding_backend":"flag","local_model_ready":true,...}
#   mode                —— numpy（预计算向量库）
#   chunk_count         —— 30532（34154 条原始 chunk 过滤非中英文后的可用数）
#   embedding_backend   —— 冷启动未加载时为 null；首次 RAG 调用后变为 "flag"（FlagEmbedding 后端）；
#                         降级时为 "st"（sentence-transformers）
#   local_model_ready   —— true 表示本地 bge-m3 模型已就绪；false 表示首次查询会尝试从 HuggingFace 在线下载（慢/易失败）

# 3) 接口文档（Swagger）
# 浏览器打开 http://localhost:8000/docs
```

主流程验证（学情诊断 → 生成 → 审核 → 裁判 → 交付）：

```bash
curl -X POST http://localhost:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"什么是RAG","session_id":"sess_001","profile":{"background":"有Python基础","knowledge_level":"中级","current_goal":"项目落地","question_type":"操作步骤","domain_hint":["RAG"]}}'
```

> 完整响应字段见 `backend/api/schemas.py` 的 `AskResponse`。
> `background` 取值：文科 / 理科_无编程 / 有Python基础 / 有ML基础
> `knowledge_level` 取值：入门 / 中级 / 进阶

### 接口一览

| 类型 | 路径 | 说明 |
|---|---|---|
| 业务 | `/api/ask`、`/api/status/{task_id}`、`/api/quiz_submit`、`/api/feedback`、`/api/kb/*`、`/api/report/{session_id}` | 见 `backend/api/routes/` |
| 实时 | `ws://localhost:8000/ws/{task_id}` | FSM 状态实时推送 |
| 运维 | `/health`、`/docs` | 健康检查 / Swagger |

---

## 7. 指标复现

```bash
export OMP_NUM_THREADS=1

# 4 项核心指标（覆盖率 / 适配 / 幻觉 / 谬误）
python -m backend.scripts.validate_metrics --bm-only
# 报告输出至 docs/metrics_validation_report.md

# 单元测试
python -m pytest backend/tests/ -v
```

---

## 8. 数据合规

- `.env`（含 API Key）已在 `.gitignore` 中，**不随源码泄露**
- 知识库来源合规处置：见 `docs/SETUP.md` 第 7 节

---

## 9. 开放评审权限（赛题提交硬要求）

赛题要求：私有仓库需开放评审权限，或提供开源链接 / 压缩包 + 云盘。

- **GitHub 开放**：`Settings → Manage access → Invite teams or people`，
  将发榜单位指定评审账号加入（或临时改为 Public 至评审结束）
- **或提供可运行交付物**：源码压缩包 + 部署说明 + 测试数据上传安全云盘，
  将链接 / 提取码 / 上传时间截图随作品提交至邮箱 `602808600@qq.com`

> **务必在 2026-09-05 前完成。**

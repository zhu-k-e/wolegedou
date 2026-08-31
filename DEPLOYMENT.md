# 部署说明（后端）

赛题：XH-202630 领域知识个性化生成与多智能体协同决策系统
组件：FastAPI 多智能体后端（`backend/`）

---

## 1. 环境要求

- **Python 3.13**（项目依赖 `FlagEmbedding` / `bge-m3`，需在 3.13 下运行；系统自带 3.10 会因缺少 FlagEmbedding 触发降级，**不可用**）
- 依赖见 `requirements.txt`
- 运行需要一个 `.env` 配置文件（含 LLM API Key、端口等），模板见 `.env.example`

---

## 2. ⚠️ OpenMP 段错误（SIGSEGV）Workaround（必读）

`bge-m3` / `FlagEmbedding` 在多线程 OpenMP 调度下偶发 **torch 段错误（SIGSEGV）**，
表现为进程无堆栈直接崩溃，与具体版本无关（OpenMP 竞态）。

**根治方法：强制单线程 OpenMP**。在启动前设置环境变量：

```bash
export OMP_NUM_THREADS=1
```

- 本地：`OMP_NUM_THREADS=1 uvicorn backend.main:app ...`
- Docker：本仓库 `Dockerfile` 已内置 `ENV OMP_NUM_THREADS=1`
- Windows（PyCharm / PowerShell）：在解释器启动环境或 `sitecustomize.py` 中设置；
  本项目 `.venv` 已附带 `sitecustomize.py` 自动设置该变量，用 `.venv/Scripts/python.exe` 运行即可。

> 评测 / benchmark 必须用项目自带的 `.venv/Scripts/python.exe`（Python 3.13 + 已装 FlagEmbedding + 已设 OMP 单线程），
> 切勿用系统 Python 3.10 跑，否则知识库降级为 Stub、指标失真。

---

## 3. 本地快速启动

```bash
cd <项目根>
python -m venv .venv            # 若尚未创建
.venv/Scripts/python.exe -m pip install -r requirements.txt

cp .env.example .env            # 然后填入 LLM_API_KEY 等
export OMP_NUM_THREADS=1        # Windows: set OMP_NUM_THREADS=1

.venv/Scripts/python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

启动后：

- 健康检查：`GET http://localhost:8000/health` → `{"status":"ok"}`
- 接口文档（Swagger）：`http://localhost:8000/docs`
- 业务路由前缀：`/api/*`（问答、状态、反馈、答题、知识库、报告）
- 实时协同状态：`/ws`（WebSocket）

---

## 4. Docker 部署

```bash
# 构建
docker build -t wolegedou-backend .

# 运行（用 --env-file 注入密钥，切勿把 .env 打进镜像）
docker run -d --name wolegedou \
  --env-file .env \
  -p 8000:8000 \
  wolegedou-backend
```

说明：

- `Dockerfile` 已内置 `ENV OMP_NUM_THREADS=1`，无需额外设置。
- `.env` **不进镜像**（含 API Key），请用 `--env-file` 或 `-e` 注入。
- **知识库切片已随镜像分发**：`data/numpy_kb/` 以 `vectors.npy.part0` / `.part1` 分卷
  随仓库提交并 `COPY` 进镜像；容器启动时由 `docker-entrypoint.sh` **自动合并**为完整
  `vectors.npy`（RAG 加载器硬性要求该文件），无需手动执行。
- **bge-m3 嵌入模型**：镜像**不内置**该模型（约 2.2GB）。容器首次启动若检测到
  `data/bge_m3_model/` 缺失，会**自动**从 hf-mirror 国内镜像 `git clone` 拉取（需外网，
  耗时视带宽）。若构建/运行环境无外网，请预先把本地已下载的 `data/bge_m3_model` 以
  `-v "$(pwd)/data:/app/data"` 挂载进容器，或构建前将其放入 `data/`。
- 如需用宿主机数据覆盖镜像内数据（如自行替换知识库），仍可加
  `-v "$(pwd)/data:/app/data"`；entrypoint 会在挂载目录上同样完成分卷合并。
- 端口默认 8000，可由 `PORT` 环境变量覆盖。

---

## 5. 知识库切片（赛题测试数据要求）

赛题要求至少提交 **1 个垂直领域的专业知识库切片**。本项目提供：

- `data/numpy_kb/`（轻量、可随镜像分发，用于离线评测与演示）
- Chroma 向量库切片（较大，单独提供 / 挂载，不并入镜像）

初始化在应用启动时自动执行（`backend/main.py` 的 `lifespan` → `init_knowledge_base`）。

---

## 6. 评测与验证

覆盖率 / 适配 / 幻觉 / 谬误 4 指标由 `backend/scripts/validate_metrics.py` 真测：

```bash
export OMP_NUM_THREADS=1
.venv/Scripts/python.exe -m backend.scripts.validate_metrics --bm-only
```

- `--bm-only`：仅评测 `bm_` 前缀的 benchmark 会话（100 条）
- `--no-kb`：跳过独立知识库召回率测试（更快聚焦 4 指标）
- 报告输出至 `docs/metrics_validation_report.md`

单元测试（含"领域知识生成准确性"核心度量逻辑）：

```bash
export OMP_NUM_THREADS=1
.venv/Scripts/python.exe -m pytest backend/tests/ -v
```

---

## 7. 开放评审权限（赛题提交硬要求）

赛题要求：私有仓库需开放评审权限；或提供开源链接 / 压缩包 + 云盘。

- **GitHub 私有仓库开放**：仓库 `Settings → Manage access → Invite teams or people`，
  将发榜单位指定评审账号加入（或可临时改为 Public 至评审结束）；
  务必在 **2026-09-05 前** 完成开放。
- **或提供可运行交付物**：源码压缩包 + 部署说明 + 测试数据，上传至安全云盘，
  将链接 / 提取码 / 上传时间截图随作品提交至邮箱 `602808600@qq.com`。

> 提交前请确认 `.env`（含 API Key）已加入 `.gitignore`，不随源码泄露。

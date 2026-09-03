# 部署全面审核报告

**审核时间**：2026-09-03  
**审核视角**：从未见过本项目的评委，按文档从零开始部署  
**审核范围**：`DEPLOYMENT.md`、`docs/SETUP.md`、`README.md`、`Dockerfile`、`docker-entrypoint.sh`、`.dockerignore`、`.env.example`、`backend/config.py`、`backend/services/rag/kb_manager.py`

---

## 1. 审核结论

**部署文档现已统一、准确，评委按文档操作可完成部署。**

本次审核发现并修复了以下类型的问题：

- 文档描述与代码实际行为不一致（启动日志、health 接口懒加载）
- 字段/配置不一致（`.env.example` 与 `config.py` 默认值不同步）
- 失效引用（`internal/` 目录不存在）
- 平台兼容性隐患（Docker entrypoint CRLF 换行符）
- 健康检查字段误导（`embedding_available` 硬编码、缺少模型就绪状态）

---

## 2. 已修复问题清单

| 序号 | 问题 | 位置 | 修复方式 |
|---|---|---|---|
| 1 | 启动日志把"Embedding 模型加载成功"列为启动阶段输出，实际为首次 RAG 查询时懒加载输出 | `DEPLOYMENT.md` §6.1 | 调整日志说明，区分启动必然输出与首次查询输出 |
| 2 | `/api/kb/health` 冷启动时 `embedding_backend` 为 `null`，文档写死 `"flag"` | `DEPLOYMENT.md` §6.2 | 补充冷启动与首次查询后的两种预期 |
| 3 | health 接口无法判断本地 bge-m3 模型是否就绪 | `backend/services/rag/kb_manager.py` | 新增 `local_model_ready` 字段 |
| 4 | `health_check()` docstring 漏写 `"numpy"` 模式 | `backend/services/rag/kb_manager.py` | 补全 docstring |
| 5 | `health_check()` 中 `embedding_available` 硬编码为 `True` | `backend/services/rag/kb_manager.py` | 改为实际依赖检查结果 |
| 6 | `internal/frontend_integration_guide.md`、`internal/KB_PROVENANCE.md` 被引用但不存在 | `docs/SETUP.md` | 新建 `internal/` 目录与两份文档 |
| 7 | `SETUP.md` 提及不存在的 `pyproject` | `docs/SETUP.md` | 删除该注释 |
| 8 | `SETUP.md` 仍提及 cloudflared 公开演示 | `docs/SETUP.md` | 明确标注仅供开发联调，不建议写入部署说明 |
| 9 | `.env.example` 与 `config.py` 的 `LLM_TIMEOUT` 不一致（240 vs 120） | `.env.example`、`backend/config.py` | 统一为 150 |
| 10 | `config.py` 默认 `host=127.0.0.1`，导致 `python backend/main.py` 无法外部访问 | `backend/config.py` | 改为 `0.0.0.0` |
| 11 | `README.md` 项目结构把 `internal/` 写成 `docs/internal/`；chunk_count 写成 34154；仍要求从网盘下载知识库 | `README.md` | 修正路径、改为 30532、改为仓库分卷 + fetch_assets.py |
| 12 | `README.md` 启动命令带 `--reload` | `README.md` | 改为无 reload 的标准启动命令 |
| 13 | Docker entrypoint 在 Windows clone 后可能出现 CRLF 换行符错误 | `Dockerfile` | 构建时自动 `sed -i 's/\r$//'` |
| 14 | Windows 用户手动合并不知如何用 CMD/PowerShell | `DEPLOYMENT.md` §4.2 | 补充 Windows 合并命令 |
| 15 | 未明确本地部署需要 Git | `docs/SETUP.md` | 新增 Git 安装提示 |

---

## 3. 仍需评委注意的事项（按影响排序）

### 🔴 必须自行准备 API Key

系统运行**必须**有 LLM API Key。评委需复制 `.env.example` 为 `.env`，并填写：

```bash
DEEPSEEK_API_KEY=sk-xxx    # DeepSeek 平台
OPENAI_API_KEY=sk-xxx      # 阿里云 DashScope（qwen-max / qwen-turbo）
```

> 配置中**没有** `LLM_API_KEY` / `LLM_BASE_URL` 这类字段，填错字段名会导致 Key 读不到。

### 🔴 必须补齐 bge-m3 模型（约 2.27GB）

该模型**不入 Git**。本地或 Docker 首次启动前需执行：

```bash
python scripts/fetch_assets.py --model-only
```

若无外网或镜像源不可用，需手动：

```bash
git clone https://hf-mirror.com/BAAI/bge-m3 data/bge_m3_model
```

### 🟡 必须先验证知识库分卷是否真实在仓库中

由于本地 `.git` 对象库损坏，无法 100% 确认 GitHub 远程实际提交了哪些文件。评委在干净环境 clone 后应第一时间执行：

```bash
git ls-files data/numpy_kb/
python scripts/fetch_assets.py --check
```

期望输出 `bge_m3: OK / numpy_kb: OK`。

### 🟡 冷启动 `/api/kb/health` 的 `embedding_backend` 为 `null` 属正常

模型为懒加载，启动后第一次调用 `/api/ask` 或 `/api/kb/search` 后才会变为 `"flag"`。

### 🟡 启动日志里看不到"Embedding 模型加载成功"属正常

该行出现在**首次 RAG 查询**时，不在 uvicorn 启动阶段。

### 🟡 必须设置 `OMP_NUM_THREADS=1`

否则 `bge-m3` / `FlagEmbedding` 在多线程 OpenMP 下偶发 torch 段错误（SIGSEGV）。

- 本地：`export OMP_NUM_THREADS=1`（Windows：`set OMP_NUM_THREADS=1`）
- Docker：`Dockerfile` 已内置该环境变量

### 🟡 Python 必须 3.13

Python 3.10 缺少 `FlagEmbedding` 会导致知识库降级为 Stub，检索失效、指标失真。

---

## 4. 评委部署验证清单

| 步骤 | 命令 | 期望结果 |
|---|---|---|
| 克隆仓库 | `git clone ...` | 仓库拉取成功 |
| 检查分卷 | `git ls-files data/numpy_kb/` | 包含 `vectors.npy.part0`、`vectors.npy.part1` 及三个 JSON |
| 检查资产 | `python scripts/fetch_assets.py --check` | `bge_m3: OK / numpy_kb: OK` |
| 配置 Key | `cp .env.example .env` 并编辑 | 文件存在且包含 `DEEPSEEK_API_KEY`、`OPENAI_API_KEY` |
| 设置 OpenMP | `export OMP_NUM_THREADS=1` | 环境变量设置成功 |
| 启动服务 | `uvicorn backend.main:app --host 0.0.0.0 --port 8000` | 日志出现 `[NumpyKB] 加载完成: 30532 chunks` |
| 健康检查 | `curl http://localhost:8000/health` | `{"status":"ok"}` |
| 知识库检查 | `curl http://localhost:8000/api/kb/health` | `mode=numpy`、`chunk_count=30532`、`local_model_ready=true` |
| 主流程验证 | `curl -X POST http://localhost:8000/api/ask ...` | 返回 `task_id`、`resource_package` 等 |

---

## 5. 未在本轮修复但需要团队决策的事项

1. **本地 `.git` 对象库损坏**：本机 `git log` / `git ls-files` 报 `bad tree object HEAD`，无法直接 commit/push。需要用户用健康副本（`C:/Users/L/AppData/Local/Temp/wld_unzip2`）修复或重新 clone 后 push。
2. **GitHub 仓库可见性/评审权限**：赛题要求私有仓库需开放评审权限或改为 Public。需在 2026-09-05 前完成。
3. **知识库来源合规**：已提供 `internal/KB_PROVENANCE.md` 说明，但建议在提交前补全来源标注或替换为授权语料。
4. **覆盖率指标**：仍为 85.8% < 90%，是提交前唯一未达标的硬指标。需 genuine 提升，严禁改匹配口径。

# 环境搭建与评审运行指南（SETUP）

本指南面向竞赛评审 / 协作同学，说明如何在干净环境中把 `wolegedou` 后端跑起来。

> **赛题提交方式（八、(二)）**：作品统一打包提交，过大则上传云盘。
> 本项目**提交包为自包含**——`data/bge_m3_model/`（约 2.27GB）与 `data/numpy_kb/`
> **已随包提供**，评委解压后无需任何外网即可运行。下列「补齐」步骤仅作自行重新获取的兜底。

两个大体积资产（不入 Git，见 `.gitignore`）：

- `data/bge_m3_model/`（约 2.27GB，BAAI/bge-m3 嵌入模型）
- `data/numpy_kb/`（预计算向量 `vectors.npy` + `documents.json` 等，30532 条）

---

## 0. 一键启动（推荐评审使用）

```bash
cd wolegedou
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
cp .env.example .env                             # 填入 DEEPSEEK_API_KEY / OPENAI_API_KEY
python scripts/start_server.py                   # 自动设 OMP、合分卷、预检、启动
```

启动器会自动设置 `OMP_NUM_THREADS=1`（避免 bge-m3 段错误）、合并知识库分卷、预检资产，
无需手动执行下方第 2、3 节。

## 1. 基础依赖

```bash
# 必须使用 Python 3.13
# ⚠️ 不可用 3.10：缺少 FlagEmbedding 会导致知识库降级为 Stub，检索失效、指标失真
cd wolegedou
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. 补齐嵌入模型 bge-m3（仅当提交包内缺失时）

模型来自 HuggingFace `BAAI/bge-m3`。提交包已含，无需下载。兜底（镜像源）：

```bash
# 方式 A：脚本（推荐）
python scripts/fetch_assets.py --model-only

# 方式 B：手动
mkdir -p data/bge_m3_model
git clone https://hf-mirror.com/BAAI/bge-m3 data/bge_m3_model
```

若镜像源不可达，可改 `https://huggingface.co/BAAI/bge-m3`。

## 3. 补齐预计算向量库 numpy_kb（仅当提交包内缺失时）

`data/numpy_kb/` 由领域语料离线构建，含 30532 条 chunk 的 1024 维向量。

**仓库已随代码提交分卷数据**（`vectors.npy` 超 GitHub 单文件 100MB 限制，拆分为 `vectors.npy.part0` / `.part1`），**提交包内已合并为完整 `vectors.npy`**。启动时 `start_server.py` 会自动合并分卷；手动：

```bash
python scripts/fetch_assets.py --check
# 期望输出：bge_m3: OK / numpy_kb: OK
```

如分卷缺失，也可手动合并：

```bash
cat data/numpy_kb/vectors.npy.part* > data/numpy_kb/vectors.npy
```

## 4. 配置

复制 `.env.example` 为 `.env`，填入 LLM API Key（qwen-max / deepseek 等）：

```bash
cp .env.example .env
# 编辑 .env，填写以下两个字段（其余均有默认值，无需改动）：
#   DEEPSEEK_API_KEY=sk-xxx   # DeepSeek 平台申请（中档模型 deepseek-chat）
#   OPENAI_API_KEY=sk-xxx     # 阿里云 DashScope 申请（qwen-max / qwen-turbo）
```

> ⚠️ 注意：配置中**没有** `LLM_API_KEY` / `LLM_BASE_URL` 这类字段，
> 字段名以 `.env.example` 为准（对应 `config.py` 的 `deepseek_api_key` / `openai_api_key`）。
> 填错字段名会导致 Key 读不到、LLM 调用失败。

> 注意：`.env` 优先级高于 `config.py` 默认值，改任何配置前先 `grep` 确认两处。

## 5. 启动与联调

```bash
# 本地调试（reload 模式）
python backend/main.py

# 或标准 uvicorn
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

接口约定与前端对接见 `internal/frontend_integration_guide.md`（《前端对接指南》），
学情诊断报告渲染格式见 `docs/report_api.md`。

> 注意：公开演示用的 cloudflared 内网穿透仅供开发联调，**不建议写入部署说明或要求评委配置**。

## 6. 资产清单（评审自检）

| 路径 | 必需 | 说明 |
|---|---|---|
| `data/bge_m3_model/` | 是 | 嵌入模型，否则检索不可用 |
| `data/numpy_kb/vectors.npy` | 是 | 预计算向量 |
| `data/numpy_kb/documents.json` | 是 | chunk 文本 |
| `data/numpy_kb/metadatas.json` `ids.json` | 是 | 元数据与 id |
| `.env` | 是 | API Key 等密钥 |
| `requirements.txt` | 是 | 依赖 |

> 所有大体积 / 密钥资产均不入库，评审通过本指南补齐即可完整复现。

## 7. 知识库来源与版权合规

检索知识库内容源于**公开 AI / LLM 技术文档与社区资料的批量抓取**，原始来源 URL 在构建时**未持久化**（见 `internal/KB_PROVENANCE.md`）。竞赛提交前须完成以下任一项：

- **补全来源标注**：重建向量库时写入每条 chunk 的 `source` 原始链接，并在项目声明中附注「仅用于研究/教学演示，侵权即下架」；
- **替换为授权语料**：采用 CC-BY 等明确授权文档或团队自建讲义，随提交附 `LICENSES` 清单。

> 在处置完成前，知识库内容仅限内部研发与教学演示使用。详细处置步骤与责任声明见 `internal/KB_PROVENANCE.md`。

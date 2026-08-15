# 环境搭建与评审运行指南（SETUP）

本指南面向竞赛评审 / 协作同学，说明如何在干净环境中把 `wolegedou` 后端跑起来。
重点解决两个**不入 Git 的大体积资产**（见 `.gitignore` 第 17-24 行）：

- `data/bge_m3_model/`（约 2.27GB，BAAI/bge-m3 嵌入模型）
- `data/numpy_kb/`（预计算向量 `vectors.npy` 约 133MB + `documents.json` 等，34154 条）

这两个目录被 `.gitignore` 排除（单文件超 GitHub 100MB 限制 + 体积过大），**克隆仓库后需按下方步骤补齐**，否则 RAG 检索不可用。

---

## 1. 基础依赖

```bash
# 建议使用 Python 3.10+
cd wolegedou
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt  # 或 pyproject 对应安装命令
```

## 2. 补齐嵌入模型 bge-m3

模型来自 HuggingFace `BAAI/bge-m3`。因 `huggingface_hub` 直连 `hf-mirror` 偶有 308 校验问题，
**推荐使用 git clone 镜像源**（已在开发机验证可用）：

```bash
# 方式 A：脚本（推荐）
python scripts/fetch_assets.py --model-only

# 方式 B：手动
mkdir -p data/bge_m3_model
git clone https://hf-mirror.com/BAAI/bge-m3 data/bge_m3_model
```

若镜像源不可达，可改 `https://huggingface.co/BAAI/bge-m3`。

## 3. 补齐预计算向量库 numpy_kb

`data/numpy_kb/` 由领域语料离线构建，含 34154 条 chunk 的 1024 维向量。

**仓库已随代码提交分卷数据**（`vectors.npy` 133MB 超过 GitHub 单文件 100MB 限制，拆分为 `vectors.npy.part0` / `.part1`，每卷约 67MB）。clone 后执行：

```bash
python scripts/fetch_assets.py --check
# 期望输出：bge_m3: OK / numpy_kb: OK
```

`fetch_assets.py --check` 会自动合并分卷生成完整的 `data/numpy_kb/vectors.npy`。

如分卷缺失，也可手动合并：

```bash
cat data/numpy_kb/vectors.npy.part* > data/numpy_kb/vectors.npy
```

## 4. 配置

复制 `.env.example` 为 `.env`，填入 LLM API Key（qwen-max / deepseek 等）：

```bash
cp .env.example .env
# 编辑 .env，设置 LLM_API_KEY / LLM_BASE_URL 等
```

> 注意：`.env` 优先级高于 `config.py` 默认值，改任何配置前先 `grep` 确认两处。

## 5. 启动与联调

```bash
# 本地调试（reload 模式）
python backend/main.py

# 或标准 uvicorn
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

接口约定与前端对接见 `internal/frontend_integration_guide.md`（《前端对接指南》）。
公开演示可用 cloudflared 内网穿透：

```bash
cloudflared tunnel --url http://localhost:8000
```

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

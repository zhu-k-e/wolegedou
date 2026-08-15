# 知识库资产说明（KB Provenance）

## 1. 资产清单与获取方式

本系统 RAG 模块依赖以下两类**不入 Git 的大体积资产**，需在干净环境中补齐：

| 路径 | 说明 | 大小 | 获取方式 |
|---|---|---|---|
| `data/bge_m3_model/` | `BAAI/bge-m3` 嵌入模型 | 约 2.27 GB | `python scripts/fetch_assets.py --model-only` 自动从 `hf-mirror.com` 克隆 |
| `data/numpy_kb/` | 预计算向量与元数据 | 约 164 MB | 已拆分为 Git 分卷，clone 后自动合并 |

### 1.1 `data/numpy_kb/` 结构

```text
data/numpy_kb/
├── documents.json          # chunk 原始文本（约 13 MB）
├── ids.json                # chunk id 列表（约 2.6 MB）
├── metadatas.json          # 分类/来源等元数据（约 16 MB）
├── vectors.npy.part0       # 向量分卷 0（约 67 MB，< GitHub 100MB 限制）
├── vectors.npy.part1       # 向量分卷 1（约 67 MB）
└── vectors.npy             # 合并后的完整向量文件（运行时生成，133 MB）
```

**合并命令**（首次 clone 后执行）：

```bash
python scripts/fetch_assets.py --check
# 若 vectors.npy 缺失，脚本会自动按 .part* 顺序合并
```

或直接：

```bash
cat data/numpy_kb/vectors.npy.part* > data/numpy_kb/vectors.npy
```

## 2. 为什么采用分卷而非网盘

- GitHub 单文件限制约 **100 MB**；`vectors.npy` 原始大小约 **133 MB**，无法直接推送。
- 压缩（gzip-9）仅能从 133 MB 降到 124 MB，仍超限。
- 采用**两分卷（每卷约 67 MB）随仓库提交**，评审 clone 后即可自动合并复现，**无需依赖外部网盘链接有效性**。

## 3. 来源与版权合规声明

当前 `data/numpy_kb/` 中的 chunk 文本主要来源于**公开 AI / LLM 技术文档与社区资料的批量抓取**，用于竞赛演示与教学研究。

提交前已满足以下任一项（竞赛/评审用途）：

- 语料为公开技术文档摘要/改写，仅用于非商业教学演示；
- 若存在侵权疑虑，可在评审阶段替换为团队自建讲义或 CC-BY 授权文档，只要保持 `vectors.npy` 维度（1024 维）与 chunk 数量一致即可。

> 本知识库内容仅限竞赛评审、教学演示与研究使用，不得用于商业传播。

## 4. 本地运行时校验

```bash
python scripts/fetch_assets.py --check
```

期望输出：

```text
bge_m3:     OK
numpy_kb:   OK
```

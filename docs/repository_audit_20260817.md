# 仓库审核报告（2026-08-17）

> 目的：提交前（9-5 截止）全仓审核，重点查大日志与提交包污染风险。
> 结论：**git 版本库本身干净**；真正风险是"手动 zip 整个文件夹"会带入数 GB 垃圾文件。

---

## 一、根目录大日志（用户重点关注）

共 **58 个 `*.log`，合计 8.77 MB**，全部被 `.gitignore` 第 8 行 `*.log` 忽略 → **不会进 git**（clone 干净）。

根目录最大几个：

| 文件 | 大小 |
|------|------|
| `benchmark_local.log` | 636 KB |
| `bm_full.log` | 443 KB |
| `benchmark_pilot.log` | 400 KB |
| `bm_kb.log` | 388 KB |
| `server_8000.log` | 357 KB |
| `benchmark_tc009.log` | 144 KB |
| `rejudge_run.log` | 102 KB |
| `benchmark_validate.log` | 104 KB |
| `bm_debug.log` | 83 KB |
| `tc001.log` | 62 KB |
| `bm_fix.log` | 50 KB |
| `diag_server*.log` ×3 | ~35 KB 各 |
| `tunnel.log` | 14 KB |

`data/` 下还有约 43 个日志（最大 `benchmark_rerun_judgerepair.log` 1.55 MB、`benchmark_rerun_20260806.log` 1.3 MB）。

⚠️ **风险点**：日志不进 git，但如果用 `zip -r 整个文件夹` 方式提交，这些会混进包里。

---

## 二、比日志更严重的提交包污染（手动 zip 才会中招）

| 文件/目录 | 体积 | git 状态 | 说明 |
|-----------|------|---------|------|
| `.venv`（Python 环境） | **2.4 GB** | 忽略 | 必须排除，否则包爆炸 |
| `.venv_test` | 602 MB | 忽略 | 同上 |
| `data/numpy_kb/vectors.npy`（完整） | **133 MB** | 忽略 | 入库的是 `.part0/.part1` 分卷（140MB），此完整文件是冗余，会重复打包 |
| `cloudflared.exe/` | 52 MB | 忽略 | 第三方穿透工具，非交付物 |
| `outputs/` | 0（空） | 忽略 | 生成产物，排除 |
| 58 个 `*.log` | 8.77 MB | 忽略 | 见上 |
| `verify_resp.json`（38K）、`e2e_demo.py`、`e2e_q2_timing.py` | 小 | 忽略 | 调试残留，排除 |

**💡 最干净解法：用 `git archive` 打提交包**（自动排除所有 gitignore 项）：

```bash
cd D:/projects/wolegedou
git archive --format=zip -o wolegedou_submission.zip HEAD
```

该命令只打包**已跟踪文件**（含 KB 分卷 `vectors.npy.part0/1`、源码、docs、`.env.example`），体积约 140MB+，不含任何 .venv/日志/完整 npy。配合云盘提交完全合规。

---

## 三、部署正确性（功能风险）

- ✅ **Docker 路径**：`docker-entrypoint.sh` 启动时自动把 `.part0/.part1` 合并为完整 `vectors.npy`（DEPLOYMENT.md 76-78 已说明）。
- ⚠️ **非 Docker 直跑路径**：`numpy_knowledge_base.py` 第 100 行 `np.load("vectors.npy")` **要求完整文件存在，不会自动合并分卷**。若评审不部署 Docker、直接 `python backend/main.py`，clone 后只有 `.part` 分卷 → KB 加载失败 → 系统开天窗。
- 建议：在 KB 加载器启动处加"分卷自动合并"（两路径都稳），或明确在 DEPLOYMENT.md 标注"**必须使用 Docker 部署**"。

---

## 四、安全合规（已通过）

- ✅ `.env`（含 API Key）、`*.db`、`*.log` 全部 gitignore，跟踪文件中**无真实密钥**。
  - 注：`data/numpy_kb/documents.json` 被密钥正则命中，实为知识库里一段代码示例文本 `openai.configure(api_key='YOUR API KEY')`（占位符），**误报，非泄露**。
- ✅ 无 `stu_`/`demo_` 数据残留（命中的 `demo_cache.py` 是合法服务、`docs/demo_*` 是合法文档）。
- ✅ KB 向量分卷 `vectors.npy.part0/1`（140MB）**已入库**，评审 clone 后有 KB 能跑系统。
- ✅ `scripts/fetch_assets.py` 已入库（模型缺失时自动拉取）。

---

## 五、推荐动作（按优先级）

1. **【必做】用 `git archive` 打包提交**（见第二节），彻底规避 .venv/日志/完整 npy 污染。不要手动 zip 整个文件夹。
2. **【必做·9-5 前】GitHub 私有仓开放评审权限或转 public**，否则评委看不到代码。
3. **【建议】修非 Docker 部署缺口**：KB 加载器启动自动合并分卷，或 DEPLOYMENT.md 明确"必须 Docker"。
4. **【可选】删除磁盘冗余**：`data/numpy_kb/vectors.npy`（完整，133MB，重新部署会由 entrypoint 重建）；58 个日志可删（不影响 git）。
5. **【可选】清理跟踪的调试脚本**：`backend/scripts/_preflight_qwenmax.py`、`_verify_clean_run.py` 等 `_` 前缀开发探针，非交付物，可移出或加 gitignore。

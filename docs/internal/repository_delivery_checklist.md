# 仓库交付检查清单（Repository Delivery Checklist）

> 项目：XH-202630 领域知识个性化生成与多智能体协同决策系统（后端）
> 用途：提交前逐项核对代码 / 配置 / 依赖 / 容器化 / 文档 / 数据 / 指标可复现 / 安全 / 评审可达性是否齐全，确认 **2026-09-05 前可开放给评审**。
> 评分构成：完整性 30 + 创新性 25 + 用户体验 15 + 实用价值 30。
> 关键时间线：提交截止 **2026-09-05** ｜ 初审 9-20 ｜ 终审 11 月。

---

## 一、核对总表

状态图例：✅ 已就绪 ｜ ⚠️ 建议修复（非阻断） ｜ ❌ 必须修复（阻断，已在本轮处理）

| # | 类别 | 检查项 | 状态 | 证据 / 说明 |
|---|------|--------|------|------|
| 1 | 代码 | 后端源码完整、可编译 | ✅ | `backend/`：`main.py` 入口 + `agents/api/core/db/services/schemas/scripts`；`py_compile` 全通过 |
| 2 | 代码 | 入口可启动（FastAPI + uvicorn） | ✅ | `backend/main.py` 存在；README 给启动命令 `uvicorn backend.main:app` |
| 3 | 配置 | 真实配置正确生效 | ✅ | `.env`：`qwen-max`(HIGH)/`deepseek-chat`(MID)/`qwen-turbo`(LOW)，dashscope 端点；`config.py` 从 `.env` 读取 |
| 4 | 配置 | **配置模板 `.env.example` 与真实部署一致** | ❌→✅ **本轮已修复** | 原为 `gpt-4o`/`gpt-4o-mini` + OpenAI 端点；已改为 `qwen-max`/`qwen-turbo` + dashscope（见第 4 节） |
| 5 | 依赖 | `requirements.txt` 完整 | ✅ | 37 行，分类（Web/LLM/校验/向量库/DB/测试/文档），命令清晰 |
| 6 | 依赖 | 版本锁定 | ⚠️ | 使用 `>=` 下限，未锁 `==`；复现可能拉到破坏性新版（尤其 `FlagEmbedding`/`torch`）。建议附 `pip freeze` 或 poetry.lock |
| 7 | 容器化 | `Dockerfile` 存在且正确 | ✅ | `python:3.13-slim` + `ENV OMP_NUM_THREADS=1`（torch 段错误 workaround）+ uvicorn 入口 |
| 8 | 容器化 | 部署文档配套 | ✅ | `DEPLOYMENT.md`（含 OMP 说明、KB 挂载、构建运行命令） |
| 9 | 文档 | 总体说明 `README.md` | ✅ | 含环境/安装/KB 部署/启动/测试/架构图 |
| 10 | 文档 | 指标验证报告 | ✅ | `docs/metrics_validation_report.md`：4 硬指标 + 第 5 节「运行日志告警说明」自辩 |
| 11 | 文档 | 前端对接指南（备查） | ✅ | `frontend_integration_guide.md`（前端队友已完成，作 API 参考/评审备查，非必需） |
| 12 | 测试 | 单元测试齐全可执行 | ✅ | `backend/tests/` 含 `test_knowledge_accuracy.py` 等；命令 `pytest backend/tests/ -v` |
| 13 | 指标可复现 | 真测脚本齐备 | ✅ | `validate_metrics.py` + `benchmark_testcases.py` + `metrics_llm_judge.py`；清空缓存重判流程已验证可复现 |
| 14 | 指标可复现 | 判定缓存不污染评审 | ❌→✅ **本轮已修复** | `backend/data/metrics_llm_judge_cache*.json` 已加入 `.gitignore`，评审 clone 后自行重判 |
| 15 | 数据 | 学情 I/O 示例 | ✅ | `data/io_examples/` 3 组差异化样本（TC-001/020/048）+ README |
| 16 | 数据 | 知识库大数据（numpy_kb 30532 chunks / raw_docs / bge-m3 2.2GB） | ⚠️ | 已 `gitignore`（体积超限）；复现需从网盘下载，`KB_PROVENANCE.md` 已说明。**需确保网盘链接 9-5 前有效** |
| 17 | 安全 | 密钥不入仓 | ✅ | `.env` 已 `gitignore`；`.idea/` 已忽略 |
| 18 | 安全 | 运行时数据库不入仓 | ✅ | `data/*.db`、`backend/data/*.db*` 已忽略 |
| 19 | 工程整洁 | LICENSE | ⚠️ | 无 LICENSE 文件。竞赛通常要求明确授权，建议补 MIT / 赛方指定许可证 |
| 20 | 工程整洁 | 根目录散落开发脚本 / 日志 | ✅ 已清理 | 已通过 `.gitignore` 排除根目录 7 个 `_*.py` 一次性脚本、`backend/scripts/_ping/_probe`、各类 `data/*_backup*.json`/`wolegedou.db.backup.*`/`_st_*.json`、`docs/test_results_*.md`、`outputs/`。`cloudflared.exe/`(54MB)、`new_sub.yaml`(含代理密码)、`diag_*.json` 早已忽略。**本地磁盘仍建议删除 `new_sub.yaml`（含 trojan 密码，纯私人上网配置）** |

---

## 二、4 项硬指标（申报值，已真测可复现）

| 指标 | 值 | 阈值 | 结论 | 测算口径 |
|------|----|------|------|----------|
| 核心知识点覆盖率 | **87.9%** | ≥90% | FAIL（诚实真值） | 关键词命中（`MetricsCalculator` 静态方法），零 LLM |
| 适配准确率 | **100%** | ≥85% | PASS | 硬化 `MetricsLLMJudge`（独立 qwen-max 重判） |
| 专业知识幻觉率 | **3%** | ≤5% | PASS | 同上，全文+练习+测验 |
| 专业知识谬误率 | **0%** | ≤3% | PASS | 同上 |

> 口径一致性：4 指标在**落库讲义**上独立重判，与生成期 38 次截断 / 1 次欠费告警解耦（详见报告第 5 节）。清空判定缓存后健康 qwen-max 重判数字小幅浮动（87.9/100/3/0），证明非旧缓存。

---

## 三、已在本轮修复的项（Blocking → 已解决）

1. **`.env.example` 模型档位陈旧**（原写 `gpt-4o`/`gpt-4o-mini` + `api.openai.com`）。
   真实部署为 `qwen-max`(HIGH)/`qwen-turbo`(LOW) + dashscope 兼容端点。若评审人照旧模板填空会用错模型。
   **已改为**：`OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`、`OPENAI_MODEL=qwen-max`、`OPENAI_MINI_MODEL=qwen-turbo`。
2. **判定缓存未忽略**：`backend/data/metrics_llm_judge_cache*.json` 原会被提交，评审 clone 后会误以为指标是旧缓存算出的（实际我们清空重判过）。
   **已加入 `.gitignore`**，评审 clone 后自行 `validate_metrics` 重判。

---

## 四、建议修复项（非阻断，但建议在 9-5 前处理）

1. **锁定依赖版本**：`requirements.txt` 改为 `==` 或附 `pip freeze > requirements.lock.txt`，避免复现环境拉到破坏性新版（FlagEmbedding / torch）。
2. **补 LICENSE**：放一个 MIT 或赛方指定许可证文件，明确代码授权。
3. **确认 KB 网盘链接有效**：`data/numpy_kb`（30532 chunks）、`data/raw_docs`、`data/bge_m3_model` 不入 Git，评审复现 KB 接地必须走网盘下载。确保 9-5 前链接有效、文档（`KB_PROVENANCE.md` / `README` 第 3 节）指向正确。
4. **清理根目录开发残留**：✅ 已通过 `.gitignore` 排除（见总表第 20 行）。仅剩 `new_sub.yaml`（含代理密码）建议从本地磁盘删除，不进仓但留在本地有泄露风险。

---

## 五、9-5 前开放仓库评审权限（⚠️ 待用户决策，不自动执行）

当前约定：**不 push GitHub、不本地 commit（等你拍板）**。以下三方案任选其一，需在 9-5 前完成：

| 方案 | 做法 | 优点 | 注意 |
|------|------|------|------|
| **A. GitHub 私有仓 + 只读邀请** | 本地 `git commit` + `git push` 到私有仓，给评审账号邀「Read」权限 | 评审可完整 clone、自行跑 `validate_metrics` 复现 4 指标；最专业 | 需你有 GitHub 账号；push 前确认密钥不入库（已忽略）；需你明确授权 |
| **B. 打包交付（网盘）** | `git archive` 导出源码 + 网盘放 KB 数据 + 配套 README 指向 | 不依赖评审有 Git 习惯；适合赛方统一收包 | 评审复现需手动解包配环境；仍要确保 KB 网盘链接有效 |
| **C. 仅演示不开放代码** | 本地跑通 + 录屏/截图交付，代码不对外 | 最省事、控制源码 | 评审无法独立复现，**不利「实用价值/完整性」得分** |

> 推荐 **A**（或 A+B 并行）：让评审能独立复现真测指标，最符合竞赛「可复现、保真」的评审预期。

---

## 六、9-5 前倒排时间表（建议）

| 日期 | 里程碑 |
|------|--------|
| 即日起 – 8 月底 | 完成本清单「建议修复项」①②；后端技术要点说明书交付队友写材料 |
| 9-1 前 | 队友完成前端体验 / 方案书 / PPT / 演示视频；确认 KB 网盘链接有效（④） |
| 9-1 ~ 9-3 | 全链路回归：Docker 构建 + `validate_metrics` 真测复跑，确认指标稳定 |
| 9-3 ~ 9-4 | 拍板「开放仓库方案」（A/B/C），执行开放动作 |
| **9-5** | **提交截止，仓库对评审可达** |

---

## 七、结论

- 代码 / 配置 / 依赖 / Dockerfile / 报告 / 测试 / 指标可复现 / 安全 **均已就绪**，无阻断性问题（原 2 个 blocking 已在本轮修复）。
- 剩余为**建议项**（锁版本、LICENSE、KB 网盘、目录整洁）与**待你决策的开放仓库方案**。
- 当前即可进入「建议项处理 + 队友材料配合 + 开放方案拍板」阶段，**9-5 前可开放**。

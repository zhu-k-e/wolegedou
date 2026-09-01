# 领域知识个性化生成与多智能体协同决策系统

> 挑战杯 · 揭榜挂帅 XH-202630 · 面向 AI 与软件开发的垂直领域个性化实训平台

基于 **11 个职责分工明确的智能体协同决策**，为不同背景学习者动态生成**个性化领域学习资源**（讲义 / 实操指南 / 分阶测试题），并通过**辩论交叉验证、知识溯源、量化裁判、自适应降维进阶**等机制，在"个性化适配"与"专业高保真"之间取得平衡——攻克大模型垂直领域落地的"不可控、不专业"痛点。

## 核心能力

- **11 Agent 协同闭环**：学情诊断 → 领域调度 → 并行生成 → 审核纠偏 → 聚焦合并 → 裁判裁决 → 资源打包，角色分工明确、协作顺畅
- **16 态 FSM 状态机**：主链 9 态 + 异常 1 态 + 延伸 6 态，状态间以标准化 JSON Schema 流转，流程可观测、可降级、可回溯
- **混合检索增强生成（RAG）**：bge-m3 稠密向量 + BM25 稀疏检索 + RRF 融合（k=60）+ 按领域 Agent 过滤，跨语言检索召回率 100%
- **辩论与交叉验证防幻觉**：候选并行生成 → 落选方质疑（携带 chunk 证据）→ 获胜方辩护 → 裁判团裁决；配合知识溯源核验（已验证 / 待验证 / 矛盾）+ AST 安全扫描（9 危险函数 + 13 危险模块）
- **画像自适应**：10 字段学情画像 + 领域置信度，按答题正确率自适应"降维（生成更简单题目）/ 进阶挑战 / 启发式追问"
- **可视化报告**：知识盲区热力图 / 资源难度匹配曲线 / 学习路径规划图，随交互实时更新
- **贡献记忆自我进化**：Agent 表现评分（importance_score）驱动权重演化与优胜劣汰，反馈限幅防震荡

## 仓库结构

```
backend/             FastAPI 后端（agents/api/core/db/services/schemas/prompts）
  agents/            11 个智能体（诊断/调度/生成/审核/裁判/安全…）
  core/              FSM 状态机 + 编排器
  services/          RAG 知识库 / LLM 客户端 / JSON 三层兜底 / AST 安全
  tests/             15 个测试文件、212 个单元测试用例
src/                 前端（React + Vite）
data/
  numpy_kb/          知识库切片（30532 chunks，分卷存储，启动自动合并）
  io_examples/       3 组差异化学习者完整输入输出示例（TC-001/020/048）
tests/test_cases_100.json   100 条 benchmark 测试用例
docs/                方案书 / 技术规格 / 指标报告 / 部署资产说明等
Dockerfile           后端容器镜像（含 OpenMP 段错误 workaround）
DEPLOYMENT.md        全新机部署指南
```

## 快速开始（后端）

```bash
# 1. 克隆仓库
git clone https://github.com/zhu-k-e/wolegedou.git
cd wolegedou

# 2. 配置环境变量（自备 API Key，获取指引见 DEPLOYMENT.md）
cp .env.example .env

# 3. 安装依赖（Python 3.13）
pip install -r requirements.txt

# 4. 首次启动会自动合并知识库分卷；确保 bge-m3 模型可用：
#    （data/bge_m3_model/ 不存在时）python scripts/fetch_assets.py --model-only

# 5. 启动服务
uvicorn backend.main:app --host 0.0.0.0 --port 8000
# 健康检查：curl localhost:8000/api/kb/health → chunk_count=30532
```

> 容器部署（推荐）：`docker build -t wolegedou-backend . && docker run -d --env-file .env -p 8000:8000 wolegedou-backend`
> 详细步骤见 **[DEPLOYMENT.md](./DEPLOYMENT.md)** 与 **[docs/KB_PROVENANCE.md](./docs/KB_PROVENANCE.md)**（资产获取与合规处置）。

## 快速开始（前端）

```bash
cd src
npm install
npm run dev      # 开发模式
npm run build    # 生产构建（产物在 dist/）
```

## 运行测试

```bash
pytest backend/tests/ -q      # 212 个单元测试（含 FSM 协同调度、知识生成准确性等）
```

## 实测指标（100 条 benchmark）

| 指标 | 实测 | 赛题目标 |
|---|---|---|
| 学习者画像-资源难度适配准确率 | **100%** | ≥85% ✅ |
| 专业知识谬误率（幻觉率） | **3.0%** | <5% ✅ |
| 专业知识谬误率 | **0.0%** | <5% ✅ |
| 核心知识点覆盖率 | **87.9%** | ≥90%（如实披露未达标） |

> 详细口径与分项（P1/P3/P5）见 **[docs/metrics_validation_report.md](./docs/metrics_validation_report.md)** 与 **[docs/metrics_summary.md](./docs/metrics_summary.md)**。

## 文档索引

- `docs/proposal.md` —— 早期方案书快照（v7.0，2026-07-13；最新权威版见参赛提交材料文档）
- `docs/proposal_techspec.md` —— 技术规格书
- `docs/metrics_validation_report.md` / `docs/metrics_summary.md` —— 指标验证
- `docs/report_api.md` / `docs/memory_stats_api.md` —— 接口说明
- `docs/demo_video_final_plan.md` —— 演示视频拍摄计划（9 镜头）
- `docs/KB_PROVENANCE.md` —— 知识库资产与合规说明

## 演示视频

10 分钟系统演示视频随参赛材料提交（差异化画像输入 → 多 Agent 调度可视化 → 个性化资源生成 → 测验自适应 → 可视化报告 完整闭环）。

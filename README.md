# 领域知识个性化生成与多智能体协同决策系统

**挑战杯揭榜挂帅 XH-202630 参赛项目**

---

## 项目简介

面向垂直领域技能培训场景，构建多Agent协同决策系统，实现：
- 学情诊断：分析学习者知识盲区与能力等级
- 个性化知识生成：基于RAG检索增强动态生成学习资源
- 多Agent交叉验证：辩论机制防控大模型幻觉

---

## 技术栈

| 组件 | 技术 | 用途 |
|------|------|------|
| Agent框架 | OpenAI SDK（兼容DeepSeek/Qwen） | 调用大模型 |
| 向量数据库 | ChromaDB + SentenceTransformers | 知识库检索 |
| 前端 | Streamlit | Web可视化界面 |
| 语言 | Python 3.11+ | 统一技术栈 |

---

## 项目结构

```text
wolegedou/
├── README.md                 # 项目说明
├── requirements.txt          # Python依赖
├── config.py                # 全局配置（LLM/知识库/Agent提示词）
├── .env.example             # 环境变量模板
├── .gitignore              # Git忽略规则
│
├── agents/                 # 多Agent模块
│   ├── __init__.py
│   ├── base_agent.py       # Agent基类（统一LLM调用接口）
│   ├── diagnosis_agent.py  # 学情诊断Agent
│   ├── generation_agent.py # 知识生成Agent
│   ├── review_agent.py     # 审核纠偏Agent
│   ├── debate_coordinator.py # 辩论仲裁Agent（核心创新点）
│   └── orchestrator.py    # 多Agent协同调度器
│
├── knowledge_base/          # RAG知识库模块
│   ├── __init__.py
│   ├── document_loader.py # 文档加载与切分
│   ├── vector_store.py     # ChromaDB向量存储封装
│   ├── retriever.py       # 知识检索器（对外接口）
│   └── build_kb.py       # 知识库构建脚本
│
├── frontend/               # Streamlit前端
│   ├── __init__.py
│   └── app.py            # 主界面（5个标签页）
│
├── utils/                  # 工具模块
│   ├── __init__.py
│   ├── logger.py          # 日志配置
│   ├── test_data.py       # 测试数据生成器
│   └── quick_test.py      # 快速测试入口
│
├── knowledge_base/data/    # 原始领域文档（放这里）
├── tests/
│   └── test_data/        # 测试数据存放
├── docs/                  # 比赛方案文档
└── logs/                 # 运行日志
```

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置API Key

复制 `.env.example` 为 `.env`，填入你的API Key：

```bash
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY=sk-你的key
```

### 3. 构建知识库

在 `knowledge_base/data/` 目录下放入领域文档（.md / .txt / .py），然后运行：

```bash
python -m knowledge_base.build_kb --dir ./knowledge_base/data
```

### 4. 运行前端

```bash
streamlit run frontend/app.py
```

浏览器打开 `http://localhost:8501`

### 5. 快速测试（无前端）

```bash
python -m utils.quick_test
```

---

## 多Agent协同流程

```
学习者输入
    │
    ▼
┌─────────────────┐
│  学情诊断Agent   │  →  输出：知识等级、强项、盲区
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  RAG知识检索    │  →  输出：相关文档片段（top-5）
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  知识生成Agent   │  →  输出：讲义、实操指南、测试题
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  审核裁判Agent   │  →  输出：通过/需修正/打回重做
└────────┬────────┘
         │
    ┌──┴──┐
    │有分歧？│── 否 ──▶ 输出最终结果
    └──┬──┘
       │ 是
       ▼
┌─────────────────┐
│  辩论仲裁Agent   │  →  交叉验证，输出最终裁定
└─────────────────┘
         │
         ▼
    最终学习资源输出
```

---

## 当前进度

- [x] 项目骨架搭建
- [x] 5个Agent基础实现
- [x] RAG知识库模块
- [x] Streamlit前端界面
- [x] 测试数据生成器
- [ ] 垂直领域选定（待定）
- [ ] 知识库文档填充
- [ ] 大模型API接入测试
- [ ] 端到端流程验证
- [ ] 比赛方案文档编写

---

## 团队

| 角色 | 成员 | 负责模块 |
|------|------|----------|
| 负责人 | 待定 | 协调 |
| Agent后端 | 待定 | agents/ |
| 知识库 | 待定 | knowledge_base/ |
| 前端+文档 | 待定 | frontend/ + docs/ |

---

## 开发计划（15天MVP）

| 阶段 | 天数 | 目标 |
|------|------|------|
| P0: 搭骨架 | Day 1-5 | 3个Agent跑通，能出结果 |
| P1: 建知识库 | Day 6-8 | 文档入库，检索命中 |
| P2: 防幻觉机制 | Day 9-12 | 辩论验证，幻觉率<5% |
| P3: 可视化 | Day 13-14 | Streamlit界面，流程可视化 |
| P4: 测试提交 | Day 15 | 测试达标，决定报名 |

---

## License

MIT

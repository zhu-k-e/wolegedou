# ============================================================
# 领域知识个性化生成与多智能体协同决策系统 — 后端镜像
# 挑战杯揭榜挂帅 XH-202630
# ============================================================
FROM python:3.13-slim

# ---- OpenMP 段错误 workaround（必设）----
# bge-m3 / FlagEmbedding 在多线程 OpenMP 调度下偶发 SIGSEGV（torch 段错误），
# 强制单线程可彻底根治。容器内同样需要此环境变量（详见 DEPLOYMENT.md）。
ENV OMP_NUM_THREADS=1

WORKDIR /app

# 先装依赖，利用镜像层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端源码（backend 为 Python 包，含 __init__.py）
COPY backend/ ./backend/

# 知识库切片（numpy_kb 轻量切片可内置；大体积 Chroma 向量库请运行时挂载，见 DEPLOYMENT.md）
# COPY data/ ./data/
VOLUME ["/app/data"]

EXPOSE 8000

# 单 worker、关闭 reload 以适配容器；PORT 可由环境变量覆盖（默认 8000）
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

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

# 安装 git：首次启动拉取 bge-m3 模型（fetch_assets.py --model-only 走 git clone hf-mirror）需要
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖，利用镜像层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端源码（backend 为 Python 包，含 __init__.py）
COPY backend/ ./backend/

# 资产补齐脚本（entrypoint 用它拉取 bge-m3 模型）
COPY scripts/fetch_assets.py ./scripts/fetch_assets.py

# 知识库切片（随镜像分发：vectors.npy.part0/part1 分卷 + documents/metadatas/ids 三个 JSON）。
# 运行时由 docker-entrypoint.sh 合并为完整 vectors.npy。
# 注意：不声明 VOLUME，避免匿名卷遮蔽已烤入的 data/；如需覆盖可用 -v 挂载宿主机 data。
COPY data/ ./data/

# 启动入口：合并分卷 + 尽力拉取 bge-m3 模型，再启动服务
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh

EXPOSE 8000

# 单 worker、关闭 reload 以适配容器；PORT 可由环境变量覆盖（默认 8000）
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

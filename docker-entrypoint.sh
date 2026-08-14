#!/bin/sh
# 容器启动入口：合并 numpy_kb 分卷 + 尽力拉取 bge-m3 嵌入模型，再启动服务。
# 仓库以 vectors.npy.part0/part1 分卷提交（避免单文件超 100MB），运行时还原为完整 vectors.npy。
set -e

NUMPY_DIR="/app/data/numpy_kb"
VECTORS="$NUMPY_DIR/vectors.npy"
MODEL_DIR="/app/data/bge_m3_model"

# 1) 合并 numpy_kb 分卷 -> 完整 vectors.npy（RAG 加载器硬性要求该文件）
if [ -f "$VECTORS" ]; then
  echo "[entrypoint] vectors.npy 已存在，跳过合并"
else
  # 按分卷序号顺序合并（version sort 可正确处理 part0/part1/.../part10）
  parts=$(ls "$NUMPY_DIR"/vectors.npy.part* 2>/dev/null | sort -V)
  if [ -n "$parts" ]; then
    echo "[entrypoint] 合并 numpy_kb 分卷 -> $VECTORS"
    cat $parts > "$VECTORS"
    echo "[entrypoint] 合并完成: $(wc -c < "$VECTORS") 字节"
  else
    echo "[entrypoint][警告] 未找到 vectors.npy 分卷，RAG 知识库将不可用"
  fi
fi

# 2) 尽力拉取 bge-m3 嵌入模型（首次需要，约 2.2GB；来自 hf-mirror 国内镜像）
if [ -f "$MODEL_DIR/config.json" ]; then
  echo "[entrypoint] bge-m3 模型已就绪"
else
  echo "[entrypoint] 未找到 bge-m3，尝试从 hf-mirror 拉取（需网络）..."
  if python scripts/fetch_assets.py --model-only 2>/dev/null; then
    echo "[entrypoint] bge-m3 拉取完成"
  else
    echo "[entrypoint][警告] bge-m3 拉取失败（可能无外网）；首次 RAG 调用将回退尝试 HF hub 下载"
  fi
fi

echo "[entrypoint] 启动应用..."
exec "$@"

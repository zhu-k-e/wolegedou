#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
一键启动器（评委 / 演示人员专用）

解决的问题：
  1. bge-m3 多线程在 Windows 上会段错误 —— 本脚本在导入任何重依赖前
     就强制设置 OMP_NUM_THREADS=1。
  2. 知识库分卷（vectors.npy.part0/part1）必须合并为完整 vectors.npy 才可被加载
     —— 本脚本在启动前自动合并（如完整文件已存在则跳过）。
  3. 模型 / 知识库缺失时给出清晰中文报错，而不是静默降级成空 RAG。

用法：
  python scripts/start_server.py                 # 默认 0.0.0.0:8000
  python scripts/start_server.py --port 8080     # 自定义端口
  python scripts/start_server.py --host 127.0.0.1

依赖：需已 pip install -r requirements.txt，且 data/ 下资产就绪（见部署说明）。
"""
import os
import sys
import subprocess

# ===== 0. 必须在任何重依赖（torch/flagembedding）之前设置，避免段错误 =====
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _red(msg: str) -> str:
    return f"\033[31m{msg}\033[0m"


def _green(msg: str) -> str:
    return f"\033[32m{msg}\033[0m"


def _yellow(msg: str) -> str:
    return f"\033[33m{msg}\033[0m"


def check_env_file() -> bool:
    """检查 .env 是否存在且含必要 key。缺失仅警告（/health 仍可起，但 LLM 调用会失败）。"""
    env_path = os.path.join(ROOT, ".env")
    if not os.path.isfile(env_path):
        print(_yellow("⚠ 未找到 .env：复制 .env.example 为 .env 并填入 "
                       "DEEPSEEK_API_KEY 与 OPENAI_API_KEY 后，LLM 生成类接口才可用。"))
        print(_yellow("  cp .env.example .env   # 然后编辑 .env 填入两个 Key"))
        return False
    with open(env_path, "r", encoding="utf-8") as f:
        content = f.read()
    missing = [k for k in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY") if f"{k}=" not in content]
    if missing:
        print(_yellow(f"⚠ .env 缺少必要字段：{', '.join(missing)}。LLM 生成类接口将不可用，"
                      "请补全后重启。"))
        return False
    print(_green("✓ .env 配置完整（DEEPSEEK_API_KEY / OPENAI_API_KEY 均已设置）"))
    return True


def ensure_kb_merged() -> bool:
    """自动合并 numpy_kb 分卷为完整 vectors.npy。返回是否就绪。"""
    kb_dir = os.path.join(ROOT, "data", "numpy_kb")
    complete = os.path.join(kb_dir, "vectors.npy")
    if os.path.isfile(complete):
        print(_green("✓ 知识库向量库已就绪：data/numpy_kb/vectors.npy"))
        return True
    part0 = os.path.join(kb_dir, "vectors.npy.part0")
    part1 = os.path.join(kb_dir, "vectors.npy.part1")
    if os.path.isfile(part0) and os.path.isfile(part1):
        print("• 检测到分卷，正在合并为完整 vectors.npy ...")
        try:
            with open(part0, "rb") as a, open(part1, "rb") as b, open(complete, "wb") as out:
                out.write(a.read())
                out.write(b.read())
            print(_green("✓ 分卷合并完成：data/numpy_kb/vectors.npy"))
            return True
        except Exception as e:  # noqa
            print(_red(f"✗ 分卷合并失败：{e}"))
            return False
    print(_red("✗ 知识库向量库缺失：既无完整 vectors.npy，也无 part0/part1 分卷。"))
    print(_red("  请从提交包中确认 data/numpy_kb/ 已解压完整，或运行 python scripts/fetch_assets.py --check"))
    return False


def check_model() -> bool:
    model_dir = os.path.join(ROOT, "data", "bge_m3_model")
    if os.path.isdir(model_dir) and any(
        f.endswith(".safetensors") or f == "config.json" for f in os.listdir(model_dir)
    ):
        print(_green("✓ 嵌入模型已就绪：data/bge_m3_model/"))
        return True
    print(_yellow("⚠ 未检测到本地 bge-m3 模型（data/bge_m3_model/）。"))
    print(_yellow("  首次 RAG 查询时会尝试从 HuggingFace 在线下载（慢/易失败）。"
                  "建议从提交包中把 data/bge_m3_model/ 解压到本目录。"))
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="多智能体协同决策系统 一键启动器")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    print("=" * 60)
    print(" 领域知识个性化生成与多智能体协同决策系统 —— 启动预检")
    print("=" * 60)
    ok_env = check_env_file()
    ok_kb = ensure_kb_merged()
    ok_model = check_model()

    if not ok_kb:
        print(_red("\n知识库未就绪，系统无法提供 RAG 检索，中止启动。"))
        return 1
    if not ok_model:
        print(_yellow("\n模型缺失：系统仍可启动，但首次查询会尝试在线下载，可能较慢或失败。"))

    print("\n" + "-" * 60)
    print(f"  即将启动：uvicorn backend.main:app --host {args.host} --port {args.port}")
    print("  启动后访问：")
    print("    · 健康检查      http://localhost:%d/health" % args.port)
    print("    · API 文档      http://localhost:%d/docs" % args.port)
    print("    · 知识库健康    http://localhost:%d/api/kb/health" % args.port)
    if not ok_env:
        print(_yellow("  （提示：未配置 API Key，生成类接口将返回错误，仅架构/检索可演示）"))
    print("-" * 60 + "\n")

    # 用同进程已设好的环境变量启动 uvicorn 子进程，确保 OMP 生效
    cmd = [
        sys.executable, "-m", "uvicorn",
        "backend.main:app",
        "--host", args.host,
        "--port", str(args.port),
    ]
    try:
        return subprocess.call(cmd, cwd=ROOT)
    except KeyboardInterrupt:
        print("\n已停止。")
        return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
部署自举（评委/陌生人一键友好）：
  · 自动创建 .venv 并安装 requirements.txt（若缺失）
  · 若无 .env，自动从 .env.example 复制
供 scripts/start_server.py 与 scripts/start_all.py 复用。

仅依赖标准库，可在导入任何重依赖（torch/flagembedding）之前安全调用。

注意：运行期实际只需 fastapi/uvicorn/pydantic/openai/numpy 等核心依赖
（知识库走 numpy_kb 预计算向量，不依赖 FlagEmbedding 在线推理）。
自举检查仅校验核心模块，避免因可选重依赖缺失而误判“未安装”并触发无谓重装。
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 运行期真正必须的依赖（不含可选的 FlagEmbedding / torch 推理依赖）
_CORE_IMPORTS = "import fastapi, uvicorn, pydantic, pydantic_settings, loguru, httpx, openai, numpy, chromadb"


def _color(c, t):
    return f"\033[{c}m{t}\033[0m" if sys.stdout.isatty() else t


def _venv_python() -> str:
    if os.name == "nt":
        return os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    return os.path.join(ROOT, ".venv", "bin", "python")


def _deps_ok(py: str) -> bool:
    try:
        subprocess.run([py, "-c", _CORE_IMPORTS],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        return False


def ensure_python_with_deps() -> str:
    """返回可运行后端的 python 路径；必要时自动建 venv + 装依赖。"""
    # 若当前已在含依赖的 venv 中，直接复用
    if sys.prefix != sys.base_prefix and _deps_ok(sys.executable):
        return sys.executable

    if sys.version_info < (3, 10):
        print(_color("31", f"✗ 当前 Python {sys.version_info.major}.{sys.version_info.minor} 过低，"
                          "请使用 Python 3.10+（推荐 3.13）。"))
        sys.exit(2)

    vpy = _venv_python()
    if not os.path.isfile(vpy):
        print(_color("33", "▶ 未检测到 .venv，正在用当前 Python 创建虚拟环境..."))
        subprocess.run([sys.executable, "-m", "venv", os.path.join(ROOT, ".venv")], check=True)

    if _deps_ok(vpy):
        return vpy

    print(_color("33", "▶ 正在安装 Python 依赖（首次需联网，约 1-3 分钟；"
                      "模型与知识库已离线内置，无需下载）..."))
    req = os.path.join(ROOT, "requirements.txt")
    try:
        subprocess.run([vpy, "-m", "pip", "install", "-r", req], check=True)
    except subprocess.CalledProcessError:
        print(_color("31", "✗ 依赖安装失败（可能无网络或 pip 异常）。请手动执行："))
        print(_color("31", f"    {vpy} -m pip install -r {req}"))
        print(_color("31", "  安装完成后再运行本启动脚本。"))
        sys.exit(1)
    return vpy


def ensure_env_file() -> bool:
    """若无 .env，从 .env.example 复制。返回最终是否存在 .env。"""
    env_path = os.path.join(ROOT, ".env")
    if os.path.isfile(env_path):
        return True
    ex = os.path.join(ROOT, ".env.example")
    if os.path.isfile(ex):
        shutil.copy(ex, env_path)
        print(_color("33", "⚠ 已从 .env.example 生成 .env。请编辑填入 OPENAI_API_KEY 与 "
                          "DEEPSEEK_API_KEY（或 DASHSCOPE_API_KEY）后再运行，否则 LLM 生成接口不可用。"))
        return True
    print(_color("31", "✗ 缺少 .env 与 .env.example，无法配置 API Key。"))
    return False

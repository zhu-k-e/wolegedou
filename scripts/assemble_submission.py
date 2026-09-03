#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
提交包组装器（自包含，评委解压即跑，无需外网）

按赛题「八、(二) 作品提交方式」：作品打包（源码 + 部署说明 + 测试数据 +
演示视频 + 方案文档 + PPT）提交至邮箱；过大则上传云盘。

本脚本把项目组装为一个【自包含】提交包目录：
  - 源码 / 文档 / 测试数据（来自仓库）
  - data/bge_m3_model/（bge-m3 嵌入模型，约 2.27GB）—— 让评委不依赖 hf-mirror
  - data/numpy_kb/（预计算向量库）—— 让评委不依赖外部网盘
  - 生成 MANIFEST.md（文件清单 / 大小 / SHA256 校验和）+ 包内快速开始说明

用法：
  python scripts/assemble_submission.py --out D:/submission/wolegedou
  python scripts/assemble_submission.py --out D:/submission/wolegedou --no-model   # 不含模型(改用网盘兜底)
  python scripts/assemble_submission.py --out D:/submission/wolegedou --video D:/path/demo.mp4

之后把 --out 目录整体压缩，按赛题命名上传云盘 / 邮件。
"""
import argparse
import hashlib
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 不入库 / 不应进提交包的目录与文件
EXCLUDE_DIRS = {
    ".git", ".venv", ".venv_test", "__pycache__",
    ".idea", ".vscode", ".workbuddy", "outputs", ".pytest_cache", "data",
}
EXCLUDE_SUFFIX = (".pyc", ".db", ".db-shm", ".db-wal", ".log", ".bak", ".backup", ".exe")
EXCLUDE_NAME = {".env", "ask_resp.json", "_sync_copied.txt"}
EXCLUDE_GLOB = ("benchmark_*.log", "server_*.log", "diag_*.log", "dist-check*")
# 仅本地调试用脚本，不进提交包
DEBUG_SCRIPT_PREFIX = ("_", "debug_")


def sha256(path: str, chunk=1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.2f} TB"


def copy_tree(src: str, dst: str, manifest: list, total: list, label: str):
    for root, dirs, files in os.walk(src):
        rel_root = os.path.relpath(root, src).replace(os.sep, "/")
        parts = rel_root.split("/")
        if any(p in EXCLUDE_DIRS for p in parts):
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fn in files:
            if fn in EXCLUDE_NAME:
                continue
            ext = os.path.splitext(fn)[1].lower()
            if ext in EXCLUDE_SUFFIX:
                continue
            if ".bak_2026" in fn:
                continue
            if fn.endswith("_debug.py") or fn.startswith(DEBUG_SCRIPT_PREFIX):
                continue
            if any(__import__("fnmatch").fnmatch(fn, g) for g in EXCLUDE_GLOB):
                continue
            if rel_root == "scripts" and fn.startswith(DEBUG_SCRIPT_PREFIX):
                continue
            # 根目录仅保留工程文件，排除实验/调试脚本与响应 dump
            if rel_root == "." and fn.endswith(".py"):
                continue
            if rel_root == "." and fn.endswith(".json") and fn not in (
                "package.json", "package-lock.json"):
                continue
            s = os.path.join(root, fn)
            d = os.path.join(dst, rel_root, fn)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)
            size = os.path.getsize(s)
            total[0] += size
            # node_modules 文件极多，跳过逐文件 sha（仅记大小 + 占位），避免 MANIFEST 爆炸
            if "node_modules" in parts:
                digest = "node_modules-skip"
            else:
                digest = sha256(s)
            manifest.append((f"{label}/{rel_root}/{fn}" if rel_root != "." else f"{label}/{fn}",
                             size, digest))


def copy_data_dir(name: str, dst_root: str, manifest: list, total: list, optional: bool):
    """复制 data/<name>（模型或 KB）。不存在则跳过/告警。"""
    src = os.path.join(ROOT, "data", name)
    if not os.path.isdir(src):
        if optional:
            print(f"  [跳过] data/{name} 不存在（评委将从网盘兜底获取）")
            return False
        print(f"  [缺失] data/{name} 不存在！")
        return False
    dst = os.path.join(dst_root, "data", name)
    cnt = 0
    sub = 0
    for root, dirs, files in os.walk(src):
        rel_dir = os.path.relpath(root, src).replace(os.sep, "/")
        # bge-m3 的 onnx 子目录为冗余（代码用 FlagEmbedding/pytorch 加载，从不加载 onnx）
        if name == "bge_m3_model" and "onnx" in rel_dir.split("/"):
            dirs[:] = []
            continue
        for fn in files:
            if fn.endswith(".log"):
                continue
            # 提交包内 numpy_kb 已合并为完整 vectors.npy，分卷不再需要
            if (name == "numpy_kb" and (fn.endswith(".part0") or fn.endswith(".part1"))):
                continue
            s = os.path.join(root, fn)
            rel = os.path.relpath(s, src).replace(os.sep, "/")
            d = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)
            size = os.path.getsize(s)
            total[0] += size
            sub += size
            manifest.append((f"data/{name}/{rel}", size, sha256(s)))
            cnt += 1
    print(f"  [已包含] data/{name}：{cnt} 个文件，{human(sub)}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="输出目录（提交包根）")
    ap.add_argument("--no-model", action="store_true", help="不含 bge-m3 模型（改由网盘兜底）")
    ap.add_argument("--video", default=None, help="演示视频路径，复制进包根 demo_video/")
    args = ap.parse_args()

    out = os.path.abspath(args.out)
    if os.path.exists(out):
        print(f"[错误] 输出目录已存在：{out}\n请先删除或换名。")
        return 1
    os.makedirs(out, exist_ok=True)

    manifest: list = []
    total = [0]

    print(">>> 组装提交包：", out)
    print("  [1/4] 源码 + 文档 + 测试数据 ...")
    copy_tree(ROOT, out, manifest, total, label="wolegedou")

    print("  [2/4] 知识库 data/numpy_kb ...")
    copy_data_dir("numpy_kb", out, manifest, total, optional=False)

    if args.no_model:
        print("  [3/4] 模型：按 --no-model 跳过（网盘兜底）")
    else:
        print("  [3/4] 嵌入模型 data/bge_m3_model ...")
        copy_data_dir("bge_m3_model", out, manifest, total, optional=True)

    if args.video:
        print("  [4/4] 演示视频 ...")
        vdst = os.path.join(out, "demo_video")
        os.makedirs(vdst, exist_ok=True)
        vfn = os.path.basename(args.video)
        shutil.copy2(args.video, os.path.join(vdst, vfn))
        sz = os.path.getsize(args.video)
        total[0] += sz
        manifest.append((f"demo_video/{vfn}", sz, sha256(args.video)))
        print(f"        已包含演示视频：{vfn} ({human(sz)})")
    else:
        print("  [4/4] 演示视频：未提供（请用 --video 指定，或单独放云盘）")

    # MANIFEST
    manifest_path = os.path.join(out, "MANIFEST.md")
    lines = ["# 提交包文件清单（SHA256）", "",
             f"- 总文件数：{len(manifest)}",
             f"- 总大小：{human(total[0])}",
             "- 校验：评委解压后可用 `certutil -hashfile <文件> SHA256`(Win) 或 `sha256sum <文件>`(Linux/Mac) 核对",
             "",
             "| 相对路径 | 大小 | SHA256 |",
             "|---|---|---|"]
    for rel, size, h in manifest:
        lines.append(f"| {rel} | {human(size)} | {h[:16]}… |")
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # 包内快速开始
    quick = os.path.join(out, "提交包快速开始.txt")
    with open(quick, "w", encoding="utf-8") as f:
        f.write(
            "领域知识个性化生成与多智能体协同决策系统 —— 提交包\n"
            "================================================\n\n"
            "本包为【自包含】提交包，解压后无需任何外网即可部署运行。\n\n"
            "一、环境准备（一次性）\n"
            "  1. 安装 Python 3.13：https://www.python.org/\n"
            "  2. 安装依赖：\n"
            "       cd wolegedou\n"
            "       python -m venv .venv\n"
            "       .venv\\Scripts\\activate        (Windows)\n"
            "       # source .venv/bin/activate   (Linux/Mac)\n"
            "       pip install -r requirements.txt\n\n"
            "二、配置 API Key（生成类接口必需）\n"
            "       cp .env.example .env\n"
            "       编辑 .env，填入 DEEPSEEK_API_KEY 与 OPENAI_API_KEY\n\n"
            "三、启动（推荐：一键同时拉起前端 + 后端）\n"
            "       python scripts/start_all.py\n"
            "   • 后端自动起在 :8000；前端（Vite）自动起在 :5176 并代理 /api、/ws 到后端。\n"
            "   • 评委浏览器打开 http://localhost:5176 即可看到完整系统：\n"
            "       创建学习任务 → 多智能体调度可视化 → 资源生成。\n"
            "   • 前置：评委机器需有 Node.js 18+（提交包内已含 node_modules，无需联网 install）。\n\n"
            "   仅后端（无界面）：\n"
            "       python scripts/start_server.py\n"
            "   或手动：\n"
            "       set OMP_NUM_THREADS=1\n"
            "       uvicorn backend.main:app --host 0.0.0.0 --port 8000\n\n"
            "四、验证\n"
            "       前端：浏览器 http://localhost:5176 （可创建任务并观察调度可视化）\n"
            "       后端 API：浏览器 http://localhost:8000/docs\n"
            "       或 curl http://localhost:8000/health  →  {\"status\":\"ok\"}\n\n"
            "五、演示视频见 demo_video/ 目录。\n"
            "详细说明见 wolegedou/DEPLOYMENT.md 与 wolegedou/docs/SETUP.md。\n"
        )

    print(f"\n>>> 完成。提交包共 {len(manifest)} 个文件，总大小 {human(total[0])}")
    print(f">>> 输出目录：{out}")
    print(f">>> 清单：{manifest_path}")
    print(f">>> 下一步：将 {out} 整体压缩，按赛题命名上传云盘 / 邮件。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

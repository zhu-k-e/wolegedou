#!/usr/bin/env python
"""评审资产补齐脚本（SETUP 步骤 2/3 用）。

仅做两件事，不触发任何 LLM 调用、不影响运行时：
  1. 下载 BAAI/bge-m3 嵌入模型到 data/bge_m3_model/（git clone hf-mirror 镜像，
     已验证可绕开 huggingface_hub 直连 308 校验问题）。
  2. 检查 data/numpy_kb/ 是否就绪；若提供 --numpy-src 则复制。

用法：
  python scripts/fetch_assets.py --model-only
  python scripts/fetch_assets.py --check
  python scripts/fetch_assets.py --numpy-src <含 vectors.npy 的目录>
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(ROOT, "data", "bge_m3_model")
NUMPY_DIR = os.path.join(ROOT, "data", "numpy_kb")
MODEL_REPO = "https://hf-mirror.com/BAAI/bge-m3"


def fetch_model() -> int:
    if os.path.isdir(MODEL_DIR) and any(os.scandir(MODEL_DIR)):
        print(f"[skip] bge_m3 已存在: {MODEL_DIR}")
        return 0
    os.makedirs(MODEL_DIR, exist_ok=True)
    print(f"[fetch] git clone {MODEL_REPO} -> {MODEL_DIR}")
    try:
        subprocess.run(
            ["git", "clone", MODEL_REPO, MODEL_DIR],
            check=True,
        )
    except FileNotFoundError:
        print("[error] 未找到 git，请先安装 Git 后重试")
        return 1
    except subprocess.CalledProcessError as e:
        print(f"[error] 克隆失败：{e}")
        print(f"        可手动执行：git clone {MODEL_REPO} {MODEL_DIR}")
        return 1
    return 0


def copy_numpy(src: str) -> int:
    if not os.path.isdir(src):
        print(f"[error] --numpy-src 不存在：{src}")
        return 1
    required = ["vectors.npy", "documents.json", "metadatas.json", "ids.json"]
    missing = [f for f in required if not os.path.exists(os.path.join(src, f))]
    if missing:
        print(f"[error] 源目录缺少必要文件：{missing}")
        return 1
    os.makedirs(NUMPY_DIR, exist_ok=True)
    for f in required:
        shutil.copy2(os.path.join(src, f), os.path.join(NUMPY_DIR, f))
    print(f"[ok] numpy_kb 已复制到 {NUMPY_DIR}")
    return 0


def merge_vectors(parts: list[str], target: str) -> int:
    """按 .part0/.part1/.partN 顺序合并成完整 vectors.npy。"""
    parts = sorted(parts, key=lambda p: int(p.split(".part")[-1]))
    print(f"[merge] 合并 {len(parts)} 个分卷 -> {target}")
    try:
        with open(target, "wb") as out:
            for part in parts:
                with open(part, "rb") as f:
                    out.write(f.read())
        print(f"[ok] 合并完成: {target}")
        return 0
    except Exception as e:
        print(f"[error] 合并失败：{e}")
        return 1


def check(auto_merge: bool = True) -> int:
    model_ok = os.path.isdir(MODEL_DIR) and any(os.scandir(MODEL_DIR))
    required = ["vectors.npy", "documents.json", "metadatas.json", "ids.json"]
    missing = [f for f in required if not os.path.exists(os.path.join(NUMPY_DIR, f))]

    # 若 vectors.npy 缺失但存在分卷，自动合并
    if "vectors.npy" in missing and auto_merge:
        parts = sorted(glob.glob(os.path.join(NUMPY_DIR, "vectors.npy.part*")))
        if parts:
            if merge_vectors(parts, os.path.join(NUMPY_DIR, "vectors.npy")) == 0:
                missing.remove("vectors.npy")
        else:
            print("[warn] 未找到 vectors.npy 分卷文件，无法自动合并")

    numpy_ok = len(missing) == 0
    print(f"bge_m3:     {'OK' if model_ok else 'MISSING -> 运行 --model-only'}")
    print(f"numpy_kb:   {'OK' if numpy_ok else f'MISSING -> {missing}'}")
    return 0 if (model_ok and numpy_ok) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-only", action="store_true", help="仅下载 bge-m3 模型")
    ap.add_argument("--numpy-src", type=str, default=None, help="numpy_kb 源目录")
    ap.add_argument("--check", action="store_true", help="仅检查资产是否就绪")
    args = ap.parse_args()

    if args.check:
        return check()
    rc = 0
    if args.model_only or not args.numpy_src:
        rc |= fetch_model()
    if args.numpy_src:
        rc |= copy_numpy(args.numpy_src)
    if not (args.model_only or args.numpy_src):
        # 默认：拉模型 + 检查向量
        rc |= fetch_model()
        rc |= check()
    return rc


if __name__ == "__main__":
    sys.exit(main())

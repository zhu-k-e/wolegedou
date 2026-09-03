#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
一键启动器（评审推荐）：同时拉起后端 + 前端，评委浏览器打开即可看到完整系统。

前端使用 Vite dev server（vite.config.js 已配置 proxy：/api、/health、/ws → 后端 8000），
因此评委只需本脚本，无需手动配置跨域或反向代理。

前置：
  - 后端：Python 3.13 + .venv（含依赖）；或系统 Python + pip install -r requirements.txt
  - 前端：已 npm install（提交包内已含 node_modules）；评委机器需有 Node.js 18+
  - .env 已填 OPENAI_API_KEY / DEEPSEEK_API_KEY（见 .env.example）

用法：
  python scripts/start_all.py                 # 后端 8000 + 前端 5176
  python scripts/start_all.py --backend-port 8000 --frontend-port 5176
  python scripts/start_all.py --host 0.0.0.0  # 允许局域网/同机其他设备访问前端

启动后访问：http://localhost:5176
"""
import argparse
import os
import signal
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 防 bge-m3 多线程段错误
for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_k, "1")


def _find_npm():
    for cand in ("npm.cmd", "npm", "npm.exe"):
        p = subprocess.sys if False else __import__("shutil").which(cand)
        if p:
            return p
    # Windows 常见位置兜底
    import glob
    for base in (r"C:\Program Files\nodejs", r"C:\Program Files (x86)\nodejs",
                 os.path.expanduser("~/.nvm/versions/node/*")):
        hits = glob.glob(os.path.join(base, cand))
        if hits:
            return hits[0]
    return None


def _find_node():
    p = __import__("shutil").which("node") or __import__("shutil").which("node.exe")
    return p


def _wait_health(url: str, timeout: int = 120) -> bool:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def _color(c, t):
    return f"\033[{c}m{t}\033[0m" if sys.stdout.isatty() else t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--backend-port", type=int, default=8000)
    ap.add_argument("--frontend-port", type=int, default=5176)
    args = ap.parse_args()

    # ---- 后端 ----
    py = sys.executable
    backend_cmd = [py, "-m", "uvicorn", "backend.main:app",
                   "--host", args.host, "--port", str(args.backend_port)]
    print(_color("36", f"▶ 启动后端 uvicorn @ http://{args.host}:{args.backend_port} ..."))
    backend = subprocess.Popen(backend_cmd, cwd=ROOT)

    if not _wait_health(f"http://127.0.0.1:{args.backend_port}/health", timeout=180):
        print(_color("31", "✗ 后端 180s 内未就绪（/health 无响应），请检查 .env 与模型/KB。"))
        backend.terminate()
        return 1
    print(_color("32", f"✓ 后端已就绪：http://{args.host}:{args.backend_port}/health"))

    # ---- 前端 ----
    node = _find_node()
    npm = _find_npm()
    if not node or not npm:
        print(_color("33", "⚠ 未检测到 Node.js / npm，跳过前端。后端已在运行；"
                          "评委可手动在装有 Node 的机器执行 `npm install && npm run dev`。"
                          "（赛题要求浏览器可视化展示，强烈建议运行前端）"))
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            backend.terminate()
        return 0

    fe_dir = ROOT  # 前端源码/配置在仓库根（vite.config.js / package.json）
    print(_color("36", f"▶ 启动前端 Vite dev @ http://{args.host}:{args.frontend_port} ..."))
    # Windows 用 npm.cmd；其余用 npm。shell=True 以保证 npm.cmd 正确解析
    frontend_cmd = [npm, "run", "dev", "--", "--host", args.host, "--port", str(args.frontend_port)]
    # 把后端地址注入前端代理（vite.config.js 读 BACKEND_URL）
    fe_env = dict(os.environ)
    fe_env["BACKEND_URL"] = f"http://localhost:{args.backend_port}"
    frontend = subprocess.Popen(frontend_cmd, cwd=fe_dir, shell=(os.name == "nt"), env=fe_env)

    print(_color("32", "=" * 60))
    print(_color("32", f"  ✓ 系统已启动！评委访问： http://{args.host}:{args.frontend_port}"))
    print(_color("32", "    后端 API    : http://%s:%d" % (args.host, args.backend_port)))
    print(_color("32", "    演示闭环    : 创建学习任务 → 多智能体调度可视化 → 资源生成"))
    print(_color("32", "=" * 60))
    print(_color("33", "  按 Ctrl+C 停止全部服务。"))

    try:
        while True:
            time.sleep(1)
            if backend.poll() is not None:
                print(_color("31", "✗ 后端进程退出，停止前端。"))
                break
            if frontend.poll() is not None:
                print(_color("31", "✗ 前端进程退出，停止后端。"))
                break
    except KeyboardInterrupt:
        print(_color("33", "\n正在停止服务..."))
    finally:
        for p in (frontend, backend):
            try:
                if p.poll() is None:
                    if os.name == "nt":
                        p.send_signal(signal.CTRL_C_EVENT)
                    else:
                        p.terminate()
                    p.wait(timeout=15)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
    print(_color("32", "已停止。"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

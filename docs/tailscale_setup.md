# Tailscale 联调指南（wolegedou 后端）

适用场景：你和前端队友**物理距离远**，需要队友稳定访问你本地运行的后端服务，
且希望地址**固定不变**（解决 cloudflared 临时隧道每次重启 URL 随机变的问题）。

> ⚠️ 重要前提：Tailscale 只解决「距离远 + URL 固定」。
> **30 秒前端超时 / 难问题超 2 分钟** 这两个痛点，必须由前端改异步轮询根治
> （见 `docs/frontend_async_api.md`），换什么穿透方式都救不了。

## 0. 免费版权益（2026-08 确认）
Tailscale Personal 免费版：**6 用户 + 无限设备**，你 + 队友两人绰绰有余，永久免费。

---

## 1. 你这边（后端开发者，Windows）

1. 下载安装 Tailscale for Windows：<https://tailscale.com/download/windows> ，双击安装。
2. 安装完成后任务栏出现 Tailscale 图标 → 点击 → **Log in** →
   用 GitHub / Google / Microsoft 任一账号登录（免费）。
3. 状态变为 `Connected` 后，系统自动分配一个 `100.x.x.x` 虚拟 IP。
4. 查看你的虚拟 IP（PowerShell）：
   ```powershell
   tailscale ip -4
   ```
   记下这个 `100.x.x.x`（例如 `100.85.12.34`）。队友就靠它访问你。
5. 确认后端服务在跑，且**监听所有网卡**（含 Tailscale 虚拟网卡）：
   ```powershell
   cd D:\projects\wolegedou
   .\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
   ```
   > 必须用 `--host 0.0.0.0`（不是 `127.0.0.1`），否则只监听本机回环，队友访问不到。
6. 邀请队友加入你的网络：
   - 浏览器打开 <https://login.tailscale.com/admin>
   - 左侧 **Users → Invite**，填入队友邮箱
   - 队友用该邮箱注册 Tailscale 账号并登录后，自动进入你的 tailnet

---

## 2. 队友那边

1. 下载安装 Tailscale（任意平台：<https://tailscale.com/download>），用自己的账号登录。
2. 接受你的邀请（你在 admin console 的 Users 页面 **Approve**）。
3. 浏览器访问 `http://<你的TailscaleIP>:8000/docs` 即可看到 Swagger 界面。

---

## 3. 前端 base URL 改动

把前端 API 基地址从 `http://localhost:8000` 或旧 cloudflared 临时 URL 改为：

```
http://<你的TailscaleIP>:8000
```

**强烈建议**同时按 `docs/frontend_async_api.md` 把同步调用改成
「提交 `/api/tasks` → 轮询 `/api/status/{task_id}` → COMPLETE 取结果」。
否则前端 30 秒超时仍在，难问题即使后端跑完 140s，前端也拿不到结果。

---

## 4. Windows 防火墙

队友首次连不上，多半是 Windows 防火墙拦了 8000 入站。任选一种：

- 首次收到入站请求时，Windows 弹窗选「允许」（勾选「专用网络」）
- 或管理员 PowerShell 手动放行：
  ```powershell
  New-NetFirewallRule -DisplayName "wolegedou-8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
  ```

---

## 5. 验证

你这边：
```powershell
tailscale status
```
应能看到你和队友的设备都在线（状态 `online`）。

队友那边浏览器开 `http://<你的IP>:8000/health`，应返回 `{"status":"ok"}`。

---

## 6. 中国大陆网络环境提醒（重要）

Tailscale 控制平面（登录/认证）和部分 DERP 中继服务器在**境外**，中国大陆网络可能遇到：

- 登录/认证偶尔需要可访问境外网络
- 若两边 NAT 打洞失败，会走 DERP 境外中继，延迟升高（此时可能比 cloudflared 无优势）
- 若 P2P 打洞成功，则直连延迟低、明显优于 cloudflared

若实测延迟高或连不上，备选方案：
- **cloudflared 固定隧道**（你配一次 `cloudflared tunnel create`，URL 固定不再每次变）
- **自建 frp**（需要一台有公网 IP 的服务器）

---

## 7. 停止服务

- 关掉 uvicorn 窗口即停后端
- 退出 Tailscale：任务栏图标 → Quit（只影响你这边可访问性，队友端无影响）

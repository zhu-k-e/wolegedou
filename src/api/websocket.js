export function connectFSM(taskId, onMessage, onClose) {
  // WS 地址动态推导：本地开发走 vite proxy（/ws），生产走同域；可用 VITE_WS_URL 覆盖
  const wsDomain = import.meta.env.VITE_WS_URL || (window.location.protocol === 'https:' ? 'wss:' : 'ws:') + '//' + window.location.host
  const wsUrl = wsDomain + `/ws/${taskId}`

  const ws = new WebSocket(wsUrl)

  ws.onopen = () => {
    console.log('FSM连接成功')
  }

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data)
    console.log('FSM状态/后端推送数据:', data)
    if (onMessage) {
      onMessage(data)
    }
  }

  ws.onerror = (error) => {
    console.error('WebSocket连接失败：', error)
  }

  ws.onclose = () => {
    console.log('FSM连接关闭')
    if (onClose) {
      onClose()
    }
  }

  return ws
}

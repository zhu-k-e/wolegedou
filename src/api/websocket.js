export function connectFSM(taskId, onMessage, onClose) {
  const wsDomain = 'wss://stations-timer-estimate-philip.trycloudflare.com'
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

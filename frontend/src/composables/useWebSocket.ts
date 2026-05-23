import { onBeforeUnmount, ref } from 'vue'

export function useWebSocket(conversationId: () => string | null, onMessage: (data: any) => void) {
  const connected = ref(false)
  const reconnecting = ref(false)
  let socket: WebSocket | null = null
  let reconnectTimer: number | null = null
  let heartbeatTimer: number | null = null
  let manualClose = false

  function wsUrl(id: string) {
    const token = localStorage.getItem('token') ?? ''
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${window.location.host}/ws/${id}?token=${encodeURIComponent(token)}`
  }

  function clearTimers() {
    if (reconnectTimer) window.clearTimeout(reconnectTimer)
    if (heartbeatTimer) window.clearInterval(heartbeatTimer)
    reconnectTimer = null
    heartbeatTimer = null
  }

  function scheduleReconnect() {
    if (manualClose || reconnectTimer) return
    reconnecting.value = true
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null
      connect()
    }, 1200)
  }

  function connect() {
    const id = conversationId()
    if (!id) return
    manualClose = false
    socket?.close()
    socket = new WebSocket(wsUrl(id))
    socket.onopen = () => {
      connected.value = true
      reconnecting.value = false
      if (heartbeatTimer) window.clearInterval(heartbeatTimer)
      heartbeatTimer = window.setInterval(() => {
        if (socket?.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: 'ping' }))
        }
      }, 25000)
    }
    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data)
        if (payload.type === 'ping') {
          socket?.send(JSON.stringify({ type: 'pong' }))
          return
        }
        onMessage(payload)
      } catch {
        /* ignore malformed socket payloads */
      }
    }
    socket.onclose = () => {
      connected.value = false
      if (heartbeatTimer) window.clearInterval(heartbeatTimer)
      heartbeatTimer = null
      scheduleReconnect()
    }
    socket.onerror = () => {
      socket?.close()
    }
  }

  function send(payload: any) {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(payload))
      return true
    }
    return false
  }

  function close() {
    manualClose = true
    clearTimers()
    socket?.close()
    socket = null
    connected.value = false
  }

  onBeforeUnmount(close)

  return { connected, reconnecting, connect, close, send }
}

import { ref } from 'vue'

export interface SSEMessage {
  event: string
  data: any
}

export function useSSE() {
  const streaming = ref(false)
  const error = ref<string | null>(null)
  let controller: AbortController | null = null

  async function postStream(url: string, body: unknown, onMessage: (message: SSEMessage) => void) {
    stop()
    controller = new AbortController()
    streaming.value = true
    error.value = null

    try {
      const token = localStorage.getItem('token')
      const response = await fetch(`/api/v1${url}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      })

      if (!response.ok || !response.body) {
        throw new Error(`SSE request failed: ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const events = buffer.split('\n\n')
        buffer = events.pop() || ''
        for (const rawEvent of events) {
          const parsed = parseEvent(rawEvent)
          if (parsed) onMessage(parsed)
        }
      }
    } catch (err: any) {
      if (err?.name !== 'AbortError') {
        error.value = err?.message || 'SSE stream failed'
      }
    } finally {
      streaming.value = false
      controller = null
    }
  }

  function stop() {
    controller?.abort()
    controller = null
    streaming.value = false
  }

  return { streaming, error, postStream, stop }
}

function parseEvent(rawEvent: string): SSEMessage | null {
  const lines = rawEvent.split('\n')
  const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim() || 'message'
  const dataText = lines
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trim())
    .join('\n')
  if (!dataText) return { event, data: null }
  try {
    return { event, data: JSON.parse(dataText) }
  } catch {
    return { event, data: dataText }
  }
}

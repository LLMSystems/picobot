import { onUnmounted, ref } from 'vue'
import { API_BASE, api } from '@/lib/api'

export type ScreencastStatus =
  | 'idle'
  | 'checking'
  | 'connecting'
  | 'live'
  | 'error'
  | 'chrome_offline'

export interface FrameMetadata {
  offsetTop?: number
  pageScaleFactor?: number
  deviceWidth?: number
  deviceHeight?: number
  scrollOffsetX?: number
  scrollOffsetY?: number
  timestamp?: number
}

function buildWsUrl(path: string): string {
  if (API_BASE) {
    return API_BASE.replace(/^http/, 'ws') + path
  }
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}${path}`
}

export function useBrowserScreencast() {
  const status = ref<ScreencastStatus>('idle')
  const frameDataUrl = ref<string | null>(null)
  const metadata = ref<FrameMetadata | null>(null)
  const errorMessage = ref<string | null>(null)
  const fps = ref(0)

  let socket: WebSocket | null = null
  let stopped = false
  let frameCount = 0
  let fpsTimer: number | null = null

  function startFpsTimer() {
    stopFpsTimer()
    fpsTimer = window.setInterval(() => {
      fps.value = frameCount
      frameCount = 0
    }, 1000)
  }

  function stopFpsTimer() {
    if (fpsTimer !== null) {
      window.clearInterval(fpsTimer)
      fpsTimer = null
    }
    frameCount = 0
    fps.value = 0
  }

  async function connect() {
    disconnect()
    stopped = false
    errorMessage.value = null
    status.value = 'checking'

    try {
      const health = await api.chromeHealth()
      if (!health.chrome_alive) {
        status.value = 'chrome_offline'
        return
      }
    } catch (e) {
      status.value = 'error'
      errorMessage.value = e instanceof Error ? e.message : '無法檢查 Chrome 狀態'
      return
    }

    if (stopped) return

    status.value = 'connecting'
    const ws = new WebSocket(buildWsUrl('/ws/browser/screencast'))
    socket = ws

    ws.onopen = () => {
      if (stopped) return
      status.value = 'live'
      startFpsTimer()
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data as string) as
          | { type: 'frame'; format: string; data: string; metadata?: FrameMetadata }
          | { type: 'error'; message: string }
        if (msg.type === 'frame') {
          frameDataUrl.value = `data:image/jpeg;base64,${msg.data}`
          metadata.value = msg.metadata ?? null
          frameCount += 1
        } else if (msg.type === 'error') {
          errorMessage.value = msg.message || 'screencast error'
          status.value = 'error'
        }
      } catch {
        // ignore malformed frames
      }
    }

    ws.onerror = () => {
      if (stopped) return
      status.value = 'error'
      if (!errorMessage.value) errorMessage.value = '連線錯誤'
      stopFpsTimer()
    }

    ws.onclose = () => {
      if (stopped) return
      if (status.value === 'live' || status.value === 'connecting') {
        status.value = 'error'
        if (!errorMessage.value) errorMessage.value = '連線已中斷'
      }
      stopFpsTimer()
    }
  }

  function sendInput(payload: Record<string, unknown>): boolean {
    if (!socket || socket.readyState !== WebSocket.OPEN) return false
    try {
      socket.send(JSON.stringify({ type: 'input', ...payload }))
      return true
    } catch {
      return false
    }
  }

  function navigate(payload: Record<string, unknown>): boolean {
    if (!socket || socket.readyState !== WebSocket.OPEN) return false
    try {
      socket.send(JSON.stringify({ type: 'navigate', ...payload }))
      return true
    } catch {
      return false
    }
  }

  function disconnect() {
    stopped = true
    stopFpsTimer()
    if (socket) {
      try {
        socket.close()
      } catch {
        // ignore
      }
      socket = null
    }
    if (status.value !== 'chrome_offline' && status.value !== 'error') {
      status.value = 'idle'
    }
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    status,
    frameDataUrl,
    metadata,
    errorMessage,
    fps,
    connect,
    disconnect,
    sendInput,
    navigate,
  }
}

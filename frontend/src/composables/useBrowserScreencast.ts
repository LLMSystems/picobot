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

export interface ViewportSettings {
  width: number
  height: number
  deviceScaleFactor?: number
  mobile?: boolean
}

export interface QualitySettings {
  maxWidth: number
  maxHeight: number
  quality: number
  everyNthFrame: number
}

type ServerMessage =
  | { type: 'frame'; format: string; data: string; targetId?: string; metadata?: FrameMetadata }
  | { type: 'target_switched'; targetId: string }
  | { type: 'tabs_changed'; destroyed?: string; currentClosed?: boolean }
  | { type: 'viewport_changed'; viewport: ViewportSettings | null }
  | { type: 'quality_changed'; quality: QualitySettings }
  | { type: 'error'; message: string }

export interface ScreencastCallbacks {
  onTabsChanged?: (info: { destroyed?: string; currentClosed?: boolean }) => void
}

function buildWsUrl(path: string): string {
  if (API_BASE) {
    return API_BASE.replace(/^http/, 'ws') + path
  }
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}${path}`
}

export function useBrowserScreencast(callbacks: ScreencastCallbacks = {}) {
  const status = ref<ScreencastStatus>('idle')
  const frameDataUrl = ref<string | null>(null)
  const metadata = ref<FrameMetadata | null>(null)
  const errorMessage = ref<string | null>(null)
  const fps = ref(0)
  const currentTargetId = ref<string | null>(null)
  const switching = ref(false)
  const viewport = ref<ViewportSettings | null>(null)
  const quality = ref<QualitySettings>({
    maxWidth: 1920,
    maxHeight: 1080,
    quality: 85,
    everyNthFrame: 1,
  })

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

  async function connect(targetId?: string) {
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
    const path = targetId
      ? `/ws/browser/screencast?targetId=${encodeURIComponent(targetId)}`
      : '/ws/browser/screencast'
    const ws = new WebSocket(buildWsUrl(path))
    socket = ws
    if (targetId) currentTargetId.value = targetId

    ws.onopen = () => {
      if (stopped) return
      status.value = 'live'
      startFpsTimer()
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data as string) as ServerMessage
        if (msg.type === 'frame') {
          frameDataUrl.value = `data:image/jpeg;base64,${msg.data}`
          metadata.value = msg.metadata ?? null
          if (msg.targetId) currentTargetId.value = msg.targetId
          frameCount += 1
          if (switching.value) switching.value = false
        } else if (msg.type === 'target_switched') {
          currentTargetId.value = msg.targetId
        } else if (msg.type === 'viewport_changed') {
          viewport.value = msg.viewport
        } else if (msg.type === 'quality_changed') {
          quality.value = msg.quality
        } else if (msg.type === 'tabs_changed') {
          callbacks.onTabsChanged?.({
            destroyed: msg.destroyed,
            currentClosed: msg.currentClosed,
          })
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

  function sendRaw(payload: Record<string, unknown>): boolean {
    if (!socket || socket.readyState !== WebSocket.OPEN) return false
    try {
      socket.send(JSON.stringify(payload))
      return true
    } catch {
      return false
    }
  }

  function setViewport(v: ViewportSettings): boolean {
    return sendRaw({ type: 'set_viewport', ...v })
  }

  function resetViewport(): boolean {
    return sendRaw({ type: 'reset_viewport' })
  }

  function setQuality(q: Partial<QualitySettings>): boolean {
    return sendRaw({ type: 'set_quality', ...q })
  }

  function switchTarget(targetId: string): boolean {
    if (!socket || socket.readyState !== WebSocket.OPEN) return false
    if (targetId === currentTargetId.value) return true
    try {
      socket.send(JSON.stringify({ type: 'switch_target', targetId }))
      // Clear current frame so the UI doesn't show the old tab while
      // the new screencast hasn't pushed a frame yet.
      switching.value = true
      frameDataUrl.value = null
      metadata.value = null
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
    switching.value = false
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
    currentTargetId,
    switching,
    viewport,
    quality,
    connect,
    disconnect,
    sendInput,
    navigate,
    switchTarget,
    setViewport,
    resetViewport,
    setQuality,
  }
}

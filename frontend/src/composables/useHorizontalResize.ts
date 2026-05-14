import { onBeforeUnmount, ref, type Ref } from 'vue'

export interface HorizontalResizeOptions {
  storageKey?: string
  initial?: number
  min?: number
  max?: number
  /** Which edge is being dragged. The opposite edge stays anchored. */
  edge?: 'left' | 'right'
}

export function useHorizontalResize(opts: HorizontalResizeOptions = {}) {
  const { storageKey, initial = 320, min = 240, max = 720, edge = 'left' } = opts

  function clamp(v: number, lo: number, hi: number): number {
    return Math.max(lo, Math.min(hi, v))
  }

  let stored: number | undefined
  if (storageKey) {
    try {
      const v = localStorage.getItem(storageKey)
      if (v) {
        const parsed = parseFloat(v)
        if (!Number.isNaN(parsed)) stored = parsed
      }
    } catch {
      // ignore
    }
  }

  const width = ref(clamp(stored ?? initial, min, max))
  const targetRef: Ref<HTMLElement | null> = ref(null)

  function persist() {
    if (!storageKey) return
    try {
      localStorage.setItem(storageKey, String(width.value))
    } catch {
      // ignore
    }
  }

  function onMove(e: PointerEvent) {
    const el = targetRef.value
    if (!el) return
    const rect = el.getBoundingClientRect()
    const next =
      edge === 'left' ? rect.right - e.clientX : e.clientX - rect.left
    const maxCap = Math.min(max, Math.floor(window.innerWidth * 0.6))
    width.value = clamp(next, min, maxCap)
  }

  function onUp() {
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
    window.removeEventListener('pointercancel', onUp)
    persist()
  }

  function onPointerDown(e: PointerEvent) {
    e.preventDefault()
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onUp)
  }

  onBeforeUnmount(() => {
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
    window.removeEventListener('pointercancel', onUp)
  })

  return { targetRef, width, onPointerDown }
}

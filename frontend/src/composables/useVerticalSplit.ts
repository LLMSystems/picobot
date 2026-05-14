import { onBeforeUnmount, ref, type Ref } from 'vue'

export interface VerticalSplitOptions {
  storageKey?: string
  initial?: number
  min?: number
  max?: number
}

export function useVerticalSplit(opts: VerticalSplitOptions = {}) {
  const { storageKey, initial = 0.5, min = 0.15, max = 0.85 } = opts

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

  const ratio = ref(clamp(stored ?? initial, min, max))
  const containerRef: Ref<HTMLElement | null> = ref(null)

  function clamp(v: number, lo: number, hi: number): number {
    return Math.max(lo, Math.min(hi, v))
  }

  function persist() {
    if (!storageKey) return
    try {
      localStorage.setItem(storageKey, String(ratio.value))
    } catch {
      // ignore
    }
  }

  function onMove(e: PointerEvent) {
    const el = containerRef.value
    if (!el) return
    const rect = el.getBoundingClientRect()
    if (rect.height <= 0) return
    const y = e.clientY - rect.top
    ratio.value = clamp(y / rect.height, min, max)
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
    document.body.style.cursor = 'row-resize'
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

  return { containerRef, ratio, onPointerDown }
}

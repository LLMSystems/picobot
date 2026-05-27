import { computed, onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '0s'
  const totalSec = Math.floor(ms / 1000)
  const h = Math.floor(totalSec / 3600)
  const m = Math.floor((totalSec % 3600) / 60)
  const s = totalSec % 60
  if (h > 0) {
    return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  }
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export function useElapsed(
  startIso: Ref<string | null | undefined> | (() => string | null | undefined),
  endIso: Ref<string | null | undefined> | (() => string | null | undefined),
  tickMs = 1000,
) {
  const now = ref(Date.now())
  let timer: number | undefined

  function resolveStart(): number | null {
    const v = typeof startIso === 'function' ? startIso() : startIso.value
    if (!v) return null
    const t = new Date(v).getTime()
    return Number.isFinite(t) ? t : null
  }

  function resolveEnd(): number | null {
    const v = typeof endIso === 'function' ? endIso() : endIso.value
    if (!v) return null
    const t = new Date(v).getTime()
    return Number.isFinite(t) ? t : null
  }

  onMounted(() => {
    timer = window.setInterval(() => {
      // Stop ticking once the end is reached, to save CPU.
      if (resolveEnd() === null) now.value = Date.now()
    }, tickMs)
  })

  onBeforeUnmount(() => {
    if (timer !== undefined) window.clearInterval(timer)
  })

  const ms = computed(() => {
    const start = resolveStart()
    if (start === null) return 0
    const end = resolveEnd() ?? now.value
    return Math.max(0, end - start)
  })

  const text = computed(() => formatDuration(ms.value))

  return { ms, text }
}

import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

export function useAutoScroll(threshold = 80) {
  const containerRef: Ref<HTMLElement | null> = ref(null)
  const pinnedToBottom = ref(true)
  let rafId: number | null = null

  function isNearBottom(): boolean {
    const el = containerRef.value
    if (!el) return true
    return el.scrollHeight - el.scrollTop - el.clientHeight < threshold
  }

  function scrollToBottom(behavior: ScrollBehavior = 'smooth') {
    const el = containerRef.value
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior })
    pinnedToBottom.value = true
  }

  function onScroll() {
    pinnedToBottom.value = isNearBottom()
  }

  onMounted(() => {
    const el = containerRef.value
    el?.addEventListener('scroll', onScroll, { passive: true })
  })

  onBeforeUnmount(() => {
    containerRef.value?.removeEventListener('scroll', onScroll)
    if (rafId !== null) cancelAnimationFrame(rafId)
  })

  function maintain() {
    if (!pinnedToBottom.value) return
    if (rafId !== null) cancelAnimationFrame(rafId)
    rafId = requestAnimationFrame(() => {
      rafId = null
      const el = containerRef.value
      if (!el) return
      el.scrollTop = el.scrollHeight
    })
  }

  return {
    containerRef,
    pinnedToBottom,
    scrollToBottom,
    maintain,
  }
}

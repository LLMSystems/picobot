import { computed, onBeforeUnmount, onMounted, ref, type Ref } from 'vue'
import { relativeTime } from '@/lib/format'

export function useRelativeTime(iso: Ref<string> | (() => string), tickMs = 60_000) {
  const now = ref(Date.now())
  let timer: number | undefined

  onMounted(() => {
    timer = window.setInterval(() => {
      now.value = Date.now()
    }, tickMs)
  })

  onBeforeUnmount(() => {
    if (timer !== undefined) window.clearInterval(timer)
  })

  const text = computed(() => {
    // touch reactivity
    void now.value
    const v = typeof iso === 'function' ? iso() : iso.value
    return relativeTime(v)
  })

  return { text }
}

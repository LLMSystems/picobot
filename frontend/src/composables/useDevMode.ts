import { computed, ref } from 'vue'

const enabled = ref(
  typeof window !== 'undefined' &&
    new URLSearchParams(window.location.search).get('dev') === '1',
)

export function useDevMode() {
  const isDev = computed(() => enabled.value)
  function toggle() {
    enabled.value = !enabled.value
  }
  return { isDev, toggle }
}

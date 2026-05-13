import { ref } from 'vue'

const pendingFill = ref<string | null>(null)
const focusToken = ref(0)

export function useComposerBus() {
  function fill(text: string) {
    pendingFill.value = text
    focusToken.value++
  }
  function focus() {
    focusToken.value++
  }
  function consume(): string | null {
    const v = pendingFill.value
    pendingFill.value = null
    return v
  }
  return { pendingFill, focusToken, fill, focus, consume }
}

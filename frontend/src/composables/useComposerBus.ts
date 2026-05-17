import { ref } from 'vue'

const pendingFill = ref<string | null>(null)
const pendingSubmit = ref(false)
const focusToken = ref(0)

export function useComposerBus() {
  function fill(text: string, opts: { submit?: boolean } = {}) {
    pendingFill.value = text
    pendingSubmit.value = opts.submit ?? false
    focusToken.value++
  }
  function focus() {
    focusToken.value++
  }
  function consume(): { text: string | null; submit: boolean } {
    const text = pendingFill.value
    const submit = pendingSubmit.value
    pendingFill.value = null
    pendingSubmit.value = false
    return { text, submit }
  }
  return { pendingFill, focusToken, fill, focus, consume }
}

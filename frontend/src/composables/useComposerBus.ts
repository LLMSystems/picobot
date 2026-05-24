import { ref } from 'vue'

export type ComposerFillMode = 'replace' | 'append'

const pendingFill = ref<string | null>(null)
const pendingSubmit = ref(false)
const pendingMode = ref<ComposerFillMode>('replace')
const focusToken = ref(0)

export function useComposerBus() {
  function fill(
    text: string,
    opts: { submit?: boolean; mode?: ComposerFillMode } = {},
  ) {
    pendingFill.value = text
    pendingSubmit.value = opts.submit ?? false
    pendingMode.value = opts.mode ?? 'replace'
    focusToken.value++
  }
  function append(text: string) {
    fill(text, { mode: 'append' })
  }
  function focus() {
    focusToken.value++
  }
  function consume(): {
    text: string | null
    submit: boolean
    mode: ComposerFillMode
  } {
    const text = pendingFill.value
    const submit = pendingSubmit.value
    const mode = pendingMode.value
    pendingFill.value = null
    pendingSubmit.value = false
    pendingMode.value = 'replace'
    return { text, submit, mode }
  }
  return { pendingFill, focusToken, fill, append, focus, consume }
}

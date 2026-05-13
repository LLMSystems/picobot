import { onBeforeUnmount, onMounted } from 'vue'

export interface ShortcutHandlers {
  onNewChat?: () => void
  onDeleteCurrent?: () => void
  onFocusComposer?: () => void
  onPrev?: () => void
  onNext?: () => void
}

export function useGlobalShortcuts(h: ShortcutHandlers) {
  function handler(e: KeyboardEvent) {
    if (e.isComposing || e.keyCode === 229) return
    const mod = e.metaKey || e.ctrlKey
    const target = e.target as HTMLElement | null
    const inEditable =
      target &&
      (target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable)

    if (mod && e.key.toLowerCase() === 'n') {
      e.preventDefault()
      h.onNewChat?.()
      return
    }
    if (mod && e.key === 'Backspace') {
      e.preventDefault()
      h.onDeleteCurrent?.()
      return
    }
    if (mod && e.key === 'ArrowUp') {
      e.preventDefault()
      h.onPrev?.()
      return
    }
    if (mod && e.key === 'ArrowDown') {
      e.preventDefault()
      h.onNext?.()
      return
    }
    if (e.key === '/' && !inEditable) {
      e.preventDefault()
      h.onFocusComposer?.()
      return
    }
  }

  onMounted(() => window.addEventListener('keydown', handler))
  onBeforeUnmount(() => window.removeEventListener('keydown', handler))
}

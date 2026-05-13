import { onMounted, ref, watch } from 'vue'

const STORAGE_KEY = 'picobot:theme'
type Theme = 'light' | 'dark'

const theme = ref<Theme>('light')

function apply(t: Theme) {
  const root = document.documentElement
  if (t === 'dark') root.classList.add('dark')
  else root.classList.remove('dark')
}

function load(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored === 'dark' || stored === 'light') return stored
  return window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light'
}

let mounted = false

export function useTheme() {
  onMounted(() => {
    if (mounted) return
    mounted = true
    theme.value = load()
    apply(theme.value)
  })

  watch(theme, (v) => {
    apply(v)
    try {
      localStorage.setItem(STORAGE_KEY, v)
    } catch {
      // ignore
    }
  })

  function toggle() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
  }

  return { theme, toggle }
}

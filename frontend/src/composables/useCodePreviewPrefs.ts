import { ref, watch } from 'vue'

const WRAP_KEY = 'picobot:preview:wrap'
const SIZE_KEY = 'picobot:preview:size'

export type CodeFontSize = 'sm' | 'md' | 'lg'

function loadWrap(): boolean {
  try {
    return localStorage.getItem(WRAP_KEY) === '1'
  } catch {
    return false
  }
}

function loadSize(): CodeFontSize {
  try {
    const v = localStorage.getItem(SIZE_KEY)
    if (v === 'sm' || v === 'md' || v === 'lg') return v
  } catch {
    // ignore
  }
  return 'sm'
}

const wrap = ref(loadWrap())
const fontSize = ref<CodeFontSize>(loadSize())

watch(wrap, (v) => {
  try {
    localStorage.setItem(WRAP_KEY, v ? '1' : '0')
  } catch {
    // ignore
  }
})

watch(fontSize, (v) => {
  try {
    localStorage.setItem(SIZE_KEY, v)
  } catch {
    // ignore
  }
})

const SIZE_ORDER: CodeFontSize[] = ['sm', 'md', 'lg']

export function useCodePreviewPrefs() {
  function toggleWrap() {
    wrap.value = !wrap.value
  }
  function bumpSize(delta: 1 | -1) {
    const i = SIZE_ORDER.indexOf(fontSize.value)
    const next = Math.max(0, Math.min(SIZE_ORDER.length - 1, i + delta))
    fontSize.value = SIZE_ORDER[next]!
  }
  return { wrap, fontSize, toggleWrap, bumpSize }
}

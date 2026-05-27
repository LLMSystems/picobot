<script lang="ts">
let globalRenderCounter = 0
let mermaidReady = false
</script>

<script setup lang="ts">
import { useTheme } from '@/composables/useTheme'
import { renderMarkdown } from '@/lib/markdown'
import mermaid from 'mermaid'
import { computed, onMounted, ref, watch } from 'vue'

const props = defineProps<{ content: string }>()

const html = computed(() => renderMarkdown(props.content))
const rootRef = ref<HTMLElement | null>(null)
const { theme } = useTheme()

const svgCache = new Map<string, string>()
let processGen = 0
let debounceTimer: number | null = null

function initMermaid() {
  mermaid.initialize({
    startOnLoad: false,
    theme: theme.value === 'dark' ? 'dark' : 'default',
    securityLevel: 'strict',
    fontFamily: 'inherit',
    logLevel: 5,
  })
  mermaidReady = true
}

function scheduleProcess() {
  if (debounceTimer !== null) window.clearTimeout(debounceTimer)
  debounceTimer = window.setTimeout(() => {
    debounceTimer = null
    void processMermaidBlocks(++processGen)
  }, 200)
}

async function processMermaidBlocks(gen: number) {
  if (!rootRef.value) return
  if (!mermaidReady) initMermaid()
  const blocks = Array.from(
    rootRef.value.querySelectorAll('code.language-mermaid'),
  )
  for (const code of blocks) {
    if (gen !== processGen) return
    const pre = code.parentElement
    if (!pre || pre.tagName !== 'PRE' || !pre.isConnected) continue
    const source = (code.textContent ?? '').trim()
    if (!source) continue

    let svg = svgCache.get(source)
    if (!svg) {
      let valid: unknown = false
      try {
        valid = await mermaid.parse(source, { suppressErrors: true })
      } catch {
        valid = false
      }
      if (!valid) continue
      if (gen !== processGen) return
      try {
        const id = `mmd-${++globalRenderCounter}`
        const result = await mermaid.render(id, source)
        svg = result.svg
        if (svg) svgCache.set(source, svg)
      } catch {
        continue
      }
    }

    if (!svg) continue
    if (gen !== processGen) return
    if (!pre.isConnected) continue

    const wrap = document.createElement('div')
    wrap.className = 'mermaid-rendered'
    wrap.innerHTML = svg
    pre.replaceWith(wrap)
  }
}

onMounted(() => {
  initMermaid()
  scheduleProcess()
})

watch(html, scheduleProcess)

watch(theme, () => {
  svgCache.clear()
  initMermaid()
  if (rootRef.value) {
    rootRef.value.innerHTML = html.value
    scheduleProcess()
  }
})
</script>

<template>
  <div
    ref="rootRef"
    class="markdown-body min-w-0 max-w-full text-sm leading-relaxed"
    v-html="html"
  />
</template>

<style>
.markdown-body {
  min-width: 0;
  max-width: 100%;
}
.markdown-body p {
  margin: 0 0 0.75em;
}
.markdown-body p:last-child {
  margin-bottom: 0;
}
.markdown-body ul,
.markdown-body ol {
  margin: 0 0 0.75em;
  padding-left: 1.25em;
}
.markdown-body ul {
  list-style: disc;
}
.markdown-body ol {
  list-style: decimal;
}
.markdown-body li {
  margin: 0.15em 0;
}
.markdown-body h1,
.markdown-body h2,
.markdown-body h3,
.markdown-body h4 {
  font-weight: 600;
  margin: 1em 0 0.5em;
  line-height: 1.3;
}
.markdown-body h1 {
  font-size: 1.4em;
}
.markdown-body h2 {
  font-size: 1.25em;
}
.markdown-body h3 {
  font-size: 1.1em;
}
.markdown-body code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  background: var(--muted);
  padding: 0.1em 0.35em;
  border-radius: 4px;
  font-size: 0.85em;
}
.markdown-body pre {
  background: var(--muted);
  border-radius: 8px;
  padding: 0.75em 1em;
  overflow-x: auto;
  margin: 0 0 0.75em;
  font-size: 0.85em;
  line-height: 1.5;
}
.markdown-body pre code,
.markdown-body pre code.hljs {
  background: transparent;
  padding: 0;
  font-size: 1em;
  color: inherit;
  display: block;
}
.markdown-body a {
  color: var(--brand);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.markdown-body blockquote {
  border-left: 3px solid var(--border);
  padding-left: 0.75em;
  margin: 0 0 0.75em;
  color: var(--muted-foreground);
}
.markdown-body table {
  border-collapse: collapse;
  margin: 0 0 0.75em;
  font-size: 0.9em;
  display: block;
  max-width: 100%;
  overflow-x: auto;
}
.markdown-body th,
.markdown-body td {
  border: 1px solid var(--border);
  padding: 0.35em 0.6em;
}
.markdown-body hr {
  border: 0;
  border-top: 1px solid var(--border);
  margin: 1em 0;
}
.markdown-body .mermaid-rendered {
  display: flex;
  justify-content: center;
  background: var(--muted);
  border-radius: 8px;
  padding: 0.75em 1em;
  margin: 0 0 0.75em;
  overflow-x: auto;
}
.markdown-body .mermaid-rendered svg {
  max-width: 100%;
  height: auto;
}
</style>

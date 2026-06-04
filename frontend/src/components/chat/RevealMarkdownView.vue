<script setup lang="ts">
import { onBeforeUnmount, ref, useAttrs, watch } from 'vue'
import DOMPurify from 'dompurify'
import MarkdownView from '@/components/common/MarkdownView.vue'
import { renderMarkdown } from '@/lib/markdown'
import { api } from '@/lib/api'

defineOptions({ inheritAttrs: false })

const props = defineProps<{
  content: string
  sessionId?: string
  streaming?: boolean
}>()
const attrs = useAttrs()

// Reveal cadence: how fast newly-streamed text is uncovered.
const REVEAL_INTERVAL_MS = 55
const MIN_CHUNK_CHARS = 12
const MAX_CHUNK_CHARS = 96

// Fade window: how long a freshly-revealed chunk keeps animating before it is
// considered "committed" (fully opaque, no longer wrapped). Split into buckets
// so we can express the per-chunk animation offset through a CSS class instead
// of an inline style (which DOMPurify would otherwise strip).
const FADE_MS = 480
const FADE_BUCKETS = 8
const FADE_BUCKET_MS = FADE_MS / FADE_BUCKETS

const visibleContent = ref(props.streaming ? '' : props.content)
const renderedHtml = ref('')
let revealTimer: number | null = null

// Each entry records the cumulative `visibleContent` length and the time that
// chunk became visible, so we can map trailing characters back to "how long
// ago were you revealed" and stagger their fade accordingly.
type RevealMark = { len: number; t: number }
let marks: RevealMark[] = []

function clearRevealTimer(): void {
  if (revealTimer === null) return
  window.clearTimeout(revealTimer)
  revealTimer = null
}

function nextChunkSize(remaining: number): number {
  if (remaining <= MIN_CHUNK_CHARS) return remaining
  return Math.max(
    MIN_CHUNK_CHARS,
    Math.min(MAX_CHUNK_CHARS, Math.ceil(remaining * 0.35)),
  )
}

function resolveOptions() {
  return props.sessionId
    ? {
        resolveImageSrc: (src: string) =>
          api.workspaceImageUrl(props.sessionId as string, src),
      }
    : undefined
}

function bucketForAge(age: number): number {
  const idx = Math.floor(age / FADE_BUCKET_MS)
  if (idx < 0) return 0
  if (idx > FADE_BUCKETS - 1) return FADE_BUCKETS - 1
  return idx
}

const SKIP_TAGS = new Set(['PRE', 'CODE', 'SCRIPT', 'STYLE', 'SVG'])

// Wrap the trailing `groups` characters of the rendered DOM in fade spans,
// newest group first. Groups are contiguous and tile the tail, so each text
// node is rebuilt once even when it hosts several groups.
function wrapTrailing(
  root: DocumentFragment,
  groups: { count: number; cls: string }[],
): void {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      let p = node.parentElement
      while (p) {
        if (SKIP_TAGS.has(p.tagName.toUpperCase())) return NodeFilter.FILTER_REJECT
        p = p.parentElement
      }
      return node.nodeValue && node.nodeValue.length
        ? NodeFilter.FILTER_ACCEPT
        : NodeFilter.FILTER_REJECT
    },
  })

  const nodes: Text[] = []
  let current: Node | null
  while ((current = walker.nextNode())) nodes.push(current as Text)

  type Seg = { node: Text; start: number; end: number; cls: string }
  const segs: Seg[] = []
  let ni = nodes.length - 1
  let endOff = ni >= 0 ? nodes[ni]!.nodeValue!.length : 0

  for (const group of groups) {
    let need = group.count
    while (need > 0 && ni >= 0) {
      if (endOff <= 0) {
        ni--
        endOff = ni >= 0 ? nodes[ni]!.nodeValue!.length : 0
        continue
      }
      const node = nodes[ni]!
      const take = Math.min(need, endOff)
      const start = endOff - take
      segs.push({ node, start, end: endOff, cls: group.cls })
      endOff = start
      need -= take
      if (endOff === 0) {
        ni--
        endOff = ni >= 0 ? nodes[ni]!.nodeValue!.length : 0
      }
    }
    if (ni < 0) break
  }

  const byNode = new Map<Text, Seg[]>()
  for (const seg of segs) {
    const list = byNode.get(seg.node) ?? []
    list.push(seg)
    byNode.set(seg.node, list)
  }

  for (const [node, list] of byNode) {
    list.sort((a, b) => a.start - b.start)
    const full = node.nodeValue ?? ''
    const parts: Node[] = []
    const head = full.slice(0, list[0]!.start)
    if (head) parts.push(document.createTextNode(head))
    for (const seg of list) {
      const span = document.createElement('span')
      span.className = seg.cls
      span.textContent = full.slice(seg.start, seg.end)
      parts.push(span)
    }
    const tail = full.slice(list[list.length - 1]!.end)
    if (tail) parts.push(document.createTextNode(tail))
    node.replaceWith(...parts)
  }
}

function buildFadedHtml(): string {
  const source = visibleContent.value
  if (!source) return ''

  const html = renderMarkdown(source, resolveOptions())
  const now = performance.now()

  // Collect the still-fading chunks, newest first, mapping each to its tail
  // character span and a fade bucket derived from its age.
  const groups: { count: number; cls: string }[] = []
  for (let i = marks.length - 1; i >= 0; i--) {
    const mark = marks[i]!
    const age = now - mark.t
    if (age >= FADE_MS) break
    const prev = i > 0 ? marks[i - 1]!.len : 0
    const count = Math.min(mark.len, source.length) - prev
    if (count > 0) {
      groups.push({ count, cls: `reveal-fade d${bucketForAge(age)}` })
    }
  }

  if (groups.length === 0) return html

  const template = document.createElement('template')
  template.innerHTML = html
  wrapTrailing(template.content, groups)
  return DOMPurify.sanitize(template.innerHTML, {
    ADD_ATTR: ['target', 'rel'],
  })
}

function rebuild(): void {
  renderedHtml.value = buildFadedHtml()
}

function grow(toLength: number): void {
  visibleContent.value = props.content.slice(0, toLength)
  marks.push({ len: visibleContent.value.length, t: performance.now() })
  // Keep the marks list bounded; anything older than the fade window is only
  // needed as the "previous length" anchor for the oldest fading chunk.
  if (marks.length > 32) marks = marks.slice(-32)
}

function revealNextChunk(): void {
  revealTimer = null
  if (!props.streaming) {
    visibleContent.value = props.content
    return
  }

  // Stream rewound or diverged (e.g. regenerate): re-reveal from scratch.
  if (!props.content.startsWith(visibleContent.value)) {
    visibleContent.value = ''
    marks = []
  }

  const remaining = props.content.length - visibleContent.value.length
  if (remaining <= 0) {
    rebuild()
    return
  }

  grow(visibleContent.value.length + nextChunkSize(remaining))
  rebuild()
  scheduleReveal()
}

function scheduleReveal(): void {
  if (!props.streaming || revealTimer !== null) return
  if (visibleContent.value.length >= props.content.length) return
  revealTimer = window.setTimeout(revealNextChunk, REVEAL_INTERVAL_MS)
}

function startReveal(): void {
  if (visibleContent.value.length === 0 && props.content.length > 0) {
    revealNextChunk()
    return
  }
  scheduleReveal()
}

watch(
  () => [props.content, props.streaming] as const,
  ([content, streaming], oldValue) => {
    const wasStreaming = oldValue?.[1] ?? false
    if (!streaming) {
      clearRevealTimer()
      visibleContent.value = content
      marks = []
      renderedHtml.value = ''
      return
    }

    if (!wasStreaming || !content.startsWith(visibleContent.value)) {
      visibleContent.value = ''
      marks = []
      renderedHtml.value = ''
    }
    startReveal()
  },
  { immediate: true },
)

onBeforeUnmount(clearRevealTimer)
</script>

<template>
  <Transition
    appear
    enter-active-class="transition duration-200 ease-out"
    enter-from-class="opacity-0 translate-y-1"
    enter-to-class="opacity-100 translate-y-0"
  >
    <MarkdownView
      v-if="!streaming && content.trim()"
      key="static"
      v-bind="attrs"
      :content="content.trim()"
      :session-id="sessionId"
    />
    <div
      v-else-if="streaming && renderedHtml"
      key="reveal"
      v-bind="attrs"
      class="markdown-body min-w-0 max-w-full text-sm leading-relaxed"
      v-html="renderedHtml"
    />
  </Transition>
</template>

<style>
@keyframes reveal-fade-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
.reveal-fade {
  display: inline;
  animation: reveal-fade-in 0.48s cubic-bezier(0.22, 0.61, 0.36, 1) both;
}
@media (prefers-reduced-motion: reduce) {
  .reveal-fade {
    animation: none;
  }
}
.reveal-fade.d1 {
  animation-delay: -0.06s;
}
.reveal-fade.d2 {
  animation-delay: -0.12s;
}
.reveal-fade.d3 {
  animation-delay: -0.18s;
}
.reveal-fade.d4 {
  animation-delay: -0.24s;
}
.reveal-fade.d5 {
  animation-delay: -0.3s;
}
.reveal-fade.d6 {
  animation-delay: -0.36s;
}
.reveal-fade.d7 {
  animation-delay: -0.42s;
}
</style>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useAttrs, watch } from 'vue'
import MarkdownView from '@/components/common/MarkdownView.vue'

defineOptions({ inheritAttrs: false })

const props = defineProps<{
  content: string
  sessionId?: string
  streaming?: boolean
}>()
const attrs = useAttrs()

const REVEAL_INTERVAL_MS = 55
const MIN_CHUNK_CHARS = 12
const MAX_CHUNK_CHARS = 96

const visibleContent = ref(props.streaming ? '' : props.content)
let revealTimer: number | null = null

const displayContent = computed(() =>
  props.streaming ? visibleContent.value : props.content,
)

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

function revealNextChunk(): void {
  revealTimer = null
  if (!props.streaming) {
    visibleContent.value = props.content
    return
  }

  if (!props.content.startsWith(visibleContent.value)) {
    visibleContent.value = props.content
    return
  }

  const remaining = props.content.slice(visibleContent.value.length)
  if (!remaining) return

  visibleContent.value += remaining.slice(0, nextChunkSize(remaining.length))
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
      return
    }

    if (!wasStreaming || !content.startsWith(visibleContent.value)) {
      visibleContent.value = ''
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
      v-if="displayContent.trim()"
      v-bind="attrs"
      :content="displayContent.trim()"
      :session-id="sessionId"
    />
  </Transition>
</template>

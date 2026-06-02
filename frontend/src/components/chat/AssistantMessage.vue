<script setup lang="ts">
import MarkdownView from '@/components/common/MarkdownView.vue'
import { Button } from '@/components/ui/button'
import type { DisplayMessage, DisplayMessageSegment } from '@/lib/types'
import { useChatStore } from '@/stores/chat'
import {
  AlertCircle,
  Brain,
  ChevronDown,
  CircleStop,
  Copy,
  LoaderCircle,
  RefreshCw,
} from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import AskUserQuestionCard from './AskUserQuestionCard.vue'
import StreamingCursor from './StreamingCursor.vue'
import ToolCallCard from './ToolCallCard.vue'

const props = defineProps<{ message: DisplayMessage }>()
const chat = useChatStore()
const sessionId = computed(() => chat.currentSessionId ?? '')

const canRegenerate = computed(
  () =>
    !chat.isStreaming &&
    (props.message.status === 'complete' ||
      props.message.status === 'aborted' ||
      props.message.status === 'error') &&
    chat.isLastAssistant(props.message.id),
)

async function regenerate() {
  try {
    await chat.regenerate(props.message.id)
  } catch (err) {
    if (err instanceof Error) {
      toast.error('重新生成失敗', { description: err.message })
    }
  }
}

const isStreaming = computed(() => props.message.status === 'streaming')
const lastSegmentIndex = computed(() => props.message.segments.length - 1)

function isReasoningSegment(
  segment: DisplayMessageSegment,
): segment is Extract<DisplayMessageSegment, { type: 'reasoning' }> {
  return segment.type === 'reasoning'
}

const reasoningSegments = computed<
  Extract<DisplayMessageSegment, { type: 'reasoning' }>[]
>(() =>
  props.message.segments
    .filter(isReasoningSegment)
    .filter((segment) => segment.content.trim() !== ''),
)


const hasReasoning = computed(() => reasoningSegments.value.length > 0)

const hasTextContent = computed(() =>
  props.message.segments.some(
    (segment) => segment.type === 'text' && segment.content.trim() !== '',
  ),
)

const showReplyPlaceholder = computed(
  () =>
    isStreaming.value &&
    !hasReasoning.value &&
    props.message.segments.length === 0,
)

const isReasoningLive = computed(
  () => isStreaming.value && hasReasoning.value && !hasTextContent.value,
)

const reasoningExpanded = ref(false)
const reasoningTouched = ref(false)

watch(
  () => props.message.id,
  () => {
    reasoningExpanded.value = false
    reasoningTouched.value = false
  },
  { immediate: true },
)

watch(
  () => ({ hasReasoning: hasReasoning.value, live: isReasoningLive.value }),
  ({ hasReasoning: nextHasReasoning, live }) => {
    if (!nextHasReasoning) {
      reasoningExpanded.value = false
      reasoningTouched.value = false
      return
    }
    if (!reasoningTouched.value) {
      reasoningExpanded.value = live
    }
  },
  { immediate: true },
)

// Index of the first text segment; everything before belongs to the reasoning phase
const firstTextSegmentIdx = computed(() => {
  const idx = props.message.segments.findIndex(
    (s) => s.type === 'text' && s.content.trim() !== '',
  )
  return idx === -1 ? props.message.segments.length : idx
})

// How many leading segments are "claimed" by the reasoning box. Only divert
// tools into the box when there is actually a reasoning box to hold them —
// otherwise a tool-only message (no reasoning, no text) would have its tool
// gated out of the main body AND have no box to render it in, leaving an empty
// bubble.
const reasoningClaimEnd = computed(() =>
  hasReasoning.value ? firstTextSegmentIdx.value : 0,
)

// Reasoning-phase segments in original order (reasoning + tool, interleaved)
const reasoningPhaseSegments = computed(() =>
  props.message.segments.slice(0, reasoningClaimEnd.value).filter((s) => {
    if (s.type === 'reasoning') return s.content.trim() !== ''
    if (s.type === 'tool') return s.toolCall.name !== 'todo_write'
    return false
  }),
)

const runtimeNotices = computed(() => props.message.runtimeNotices ?? [])

function toggleReasoning() {
  if (!hasReasoning.value) return
  reasoningTouched.value = true
  reasoningExpanded.value = !reasoningExpanded.value
}

function noticeClass(kind: 'info' | 'success' | 'warning' | 'error'): string {
  switch (kind) {
    case 'success':
      return 'text-emerald-600 dark:text-emerald-400'
    case 'warning':
      return 'text-amber-600 dark:text-amber-400'
    case 'error':
      return 'text-destructive'
    default:
      return 'text-muted-foreground'
  }
}

async function copy() {
  try {
    await navigator.clipboard.writeText(props.message.content)
    toast.success('已複製回覆')
  } catch {
    toast.error('複製失敗')
  }
}
</script>

<template>
  <div class="group">
    <div class="flex min-w-0 flex-col gap-2">
      <div v-if="hasReasoning" class="overflow-hidden rounded-2xl border border-border/60">
        <button
          type="button"
          class="flex w-full items-center gap-2.5 px-4 py-2 text-left transition-colors hover:bg-muted/40"
          :aria-expanded="reasoningExpanded"
          @click="toggleReasoning"
        >
          <div class="flex size-7 shrink-0 items-center justify-center rounded-full bg-indigo-100/80 dark:bg-indigo-500/15">
            <LoaderCircle
              v-if="isReasoningLive"
              class="size-4 animate-spin text-indigo-600 dark:text-indigo-400"
            />
            <Brain v-else class="size-4 text-indigo-600 dark:text-indigo-400" />
          </div>
          <span class="text-sm font-semibold text-foreground">思考過程</span>
          <span
            v-if="isReasoningLive"
            class="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-500/15 dark:text-amber-300"
          >
            思考中
          </span>
          <span
            v-else
            class="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400"
          >
            已完成
          </span>
          <ChevronDown
            class="ml-auto size-4 shrink-0 text-muted-foreground transition-transform"
            :class="{ 'rotate-180': reasoningExpanded }"
          />
        </button>

        <div
          v-if="reasoningExpanded"
          class="space-y-3 border-t border-border/40 px-4 pb-4 pt-3"
        >
          <template v-for="(seg, i) in reasoningPhaseSegments" :key="i">
            <MarkdownView
              v-if="seg.type === 'reasoning'"
              :content="seg.content.trim()"
              class="text-sm text-muted-foreground"
            />
            <ToolCallCard
              v-else-if="seg.type === 'tool'"
              :tool-call="seg.toolCall"
            />
          </template>
        </div>
      </div>

      <template v-for="(seg, idx) in message.segments" :key="idx">
        <AskUserQuestionCard
          v-if="seg.type === 'tool' && seg.toolCall.name === 'ask_user_question' && idx >= reasoningClaimEnd"
          :tool-call="seg.toolCall"
          :session-id="sessionId"
        />
        <ToolCallCard
          v-else-if="seg.type === 'tool' && seg.toolCall.name !== 'todo_write' && idx >= reasoningClaimEnd"
          :tool-call="seg.toolCall"
        />
        <div v-else-if="seg.type === 'text' && seg.content.trim()" class="relative">
          <MarkdownView :content="seg.content.trim()" :session-id="sessionId" />
          <StreamingCursor
            v-if="isStreaming && idx === lastSegmentIndex"
          />
        </div>
      </template>

      <div
        v-if="message.status === 'complete' && message.segments.length === 0"
        class="flex items-center gap-1.5 text-sm italic text-muted-foreground"
      >
        <AlertCircle class="size-3.5 shrink-0" />
        本次回覆沒有可顯示內容，可能只完成了工具操作或已達到輸出限制。
      </div>

      <div
        v-if="showReplyPlaceholder"
        class="flex items-center gap-2 text-sm text-muted-foreground"
      >
        <span class="flex gap-1">
          <span class="size-1.5 animate-pulse rounded-full bg-current [animation-delay:-0.3s]" />
          <span class="size-1.5 animate-pulse rounded-full bg-current [animation-delay:-0.15s]" />
          <span class="size-1.5 animate-pulse rounded-full bg-current" />
        </span>
        <span>正在回覆</span>
      </div>

      <div
        v-if="message.status === 'aborted'"
        class="flex items-center gap-1.5 text-xs italic text-muted-foreground"
      >
        <CircleStop class="size-3.5" />
        已停止回覆，這是中斷前收到的內容。
      </div>

      <div
        v-if="message.status === 'error'"
        class="flex items-center gap-1.5 text-xs text-destructive"
      >
        <AlertCircle class="size-3.5" />
        這次回覆發生錯誤。
      </div>

      <div
        v-for="notice in runtimeNotices"
        :key="notice.key"
        class="text-xs"
        :class="noticeClass(notice.kind)"
      >
        {{ notice.text }}
      </div>
    </div>

    <div
      v-if="message.status === 'complete' && (message.usage || message.toolsUsed?.length)"
      class="hidden items-center gap-2 text-[11px] text-muted-foreground group-hover:flex"
    >
      <span v-if="message.usage">
        tokens: {{ message.usage.total_tokens }}
      </span>
      <span v-if="message.toolsUsed?.length">
        tools: {{ message.toolsUsed.join(', ') }}
      </span>
    </div>

    <div
      v-if="
        hasTextContent &&
        (message.status === 'complete' ||
          message.status === 'aborted' ||
          message.status === 'error')
      "
      class="hidden items-center gap-1 group-hover:flex"
    >
      <Button
        v-if="message.status === 'complete'"
        variant="ghost"
        size="icon"
        class="size-7"
        aria-label="複製"
        @click="copy"
      >
        <Copy class="size-3.5" />
      </Button>
      <Button
        v-if="canRegenerate"
        variant="ghost"
        size="icon"
        class="size-7"
        aria-label="重新生成"
        title="重新生成"
        @click="regenerate"
      >
        <RefreshCw class="size-3.5" />
      </Button>
    </div>
  </div>
</template>

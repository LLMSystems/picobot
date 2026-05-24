<script setup lang="ts">
import { computed } from 'vue'
import { Button } from '@/components/ui/button'
import { Copy, AlertCircle, CircleStop, RefreshCw } from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import MarkdownView from '@/components/common/MarkdownView.vue'
import StreamingCursor from './StreamingCursor.vue'
import ToolCallCard from './ToolCallCard.vue'
import { useChatStore } from '@/stores/chat'
import type { DisplayMessage } from '@/lib/types'

const props = defineProps<{ message: DisplayMessage }>()
const chat = useChatStore()

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
      toast.error('重新產生失敗', { description: err.message })
    }
  }
}

const showThinking = computed(
  () =>
    props.message.status === 'streaming' &&
    props.message.segments.length === 0,
)

const isStreaming = computed(() => props.message.status === 'streaming')

const lastSegmentIndex = computed(() => props.message.segments.length - 1)

async function copy() {
  try {
    await navigator.clipboard.writeText(props.message.content)
    toast.success('已複製')
  } catch {
    toast.error('複製失敗')
  }
}
</script>

<template>
  <div class="group">
    <div class="flex min-w-0 flex-col gap-2">
      <template v-for="(seg, idx) in message.segments" :key="idx">
        <ToolCallCard v-if="seg.type === 'tool'" :tool-call="seg.toolCall" />
        <div v-else-if="seg.content" class="relative">
          <MarkdownView :content="seg.content" />
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
        回應內容為空，可能已達 token 上限或工具參數解析失敗
      </div>

      <div v-if="showThinking" class="flex items-center gap-2 text-sm text-muted-foreground">
        <span class="flex gap-1">
          <span class="size-1.5 animate-pulse rounded-full bg-current [animation-delay:-0.3s]" />
          <span class="size-1.5 animate-pulse rounded-full bg-current [animation-delay:-0.15s]" />
          <span class="size-1.5 animate-pulse rounded-full bg-current" />
        </span>
        <span>思考中…</span>
      </div>

      <div
        v-if="message.status === 'aborted'"
        class="flex items-center gap-1.5 text-xs italic text-muted-foreground"
      >
        <CircleStop class="size-3.5" />
        已中止（後端可能仍在處理）
      </div>

      <div
        v-if="message.status === 'error'"
        class="flex items-center gap-1.5 text-xs text-destructive"
      >
        <AlertCircle class="size-3.5" />
        產生回應時發生錯誤
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
          message.status === 'complete' ||
          message.status === 'aborted' ||
          message.status === 'error'
        "
        class="flex items-center gap-1 opacity-0 transition group-hover:opacity-100"
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
          aria-label="重新產生"
          title="重新產生"
          @click="regenerate"
        >
          <RefreshCw class="size-3.5" />
        </Button>
      </div>
    </div>
  </div>
</template>

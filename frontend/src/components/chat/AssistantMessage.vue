<script setup lang="ts">
import { computed } from 'vue'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Bot, Copy, AlertCircle, CircleStop } from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import MarkdownView from '@/components/common/MarkdownView.vue'
import StreamingCursor from './StreamingCursor.vue'
import ToolCallCard from './ToolCallCard.vue'
import type { DisplayMessage } from '@/lib/types'

const props = defineProps<{ message: DisplayMessage }>()

const showThinking = computed(
  () =>
    props.message.status === 'streaming' &&
    !props.message.content &&
    props.message.toolCalls.length === 0,
)

const isStreaming = computed(() => props.message.status === 'streaming')

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
  <div class="group flex gap-3">
    <Avatar class="size-8 shrink-0">
      <AvatarFallback class="bg-primary/10 text-primary">
        <Bot class="size-4" />
      </AvatarFallback>
    </Avatar>
    <div class="flex min-w-0 flex-1 flex-col gap-2 pt-1">
      <ToolCallCard
        v-for="tc in message.toolCalls"
        :key="tc.id"
        :tool-call="tc"
      />

      <div v-if="showThinking" class="flex items-center gap-2 text-sm text-muted-foreground">
        <span class="flex gap-1">
          <span class="size-1.5 animate-pulse rounded-full bg-current [animation-delay:-0.3s]" />
          <span class="size-1.5 animate-pulse rounded-full bg-current [animation-delay:-0.15s]" />
          <span class="size-1.5 animate-pulse rounded-full bg-current" />
        </span>
        <span>思考中…</span>
      </div>

      <div v-if="message.content" class="relative">
        <MarkdownView :content="message.content" />
        <StreamingCursor v-if="isStreaming" />
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
        v-if="message.status === 'complete'"
        class="flex items-center gap-1 opacity-0 transition group-hover:opacity-100"
      >
        <Button
          variant="ghost"
          size="icon"
          class="size-7"
          aria-label="複製"
          @click="copy"
        >
          <Copy class="size-3.5" />
        </Button>
      </div>
    </div>
  </div>
</template>

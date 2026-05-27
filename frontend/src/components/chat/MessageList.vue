<script setup lang="ts">
import { computed, watch } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useAutoScroll } from '@/composables/useAutoScroll'
import UserMessage from './UserMessage.vue'
import AssistantMessage from './AssistantMessage.vue'
import SubagentResultCard from './SubagentResultCard.vue'
import EmptyState from './EmptyState.vue'
import ScrollToBottom from '@/components/common/ScrollToBottom.vue'
import { Skeleton } from '@/components/ui/skeleton'
import { useComposerBus } from '@/composables/useComposerBus'
import type { DisplayMessage } from '@/lib/types'

const chat = useChatStore()
const { containerRef, pinnedToBottom, scrollToBottom, maintain } =
  useAutoScroll(80)
const composerBus = useComposerBus()

const items = computed(() => {
  const result = [...chat.messages]
  if (chat.streamingMessage) result.push(chat.streamingMessage)
  if (chat.autoResumeMessage) result.push(chat.autoResumeMessage)
  // Cards that arrived mid-stream — they belong after the currently-streaming
  // bubble, then get flushed into `messages` on commit.
  if (chat.deferredMessages.length > 0) result.push(...chat.deferredMessages)
  return result
})

function isToolOnlyAssistant(m: DisplayMessage): boolean {
  if (m.role !== 'assistant') return false
  if (m.segments.length === 0) return false
  return !m.segments.some(
    (s) => s.type === 'text' && s.content.trim() !== '',
  )
}

// Any card-style message: tool-only assistant or subagent_result card.
// Adjacent compact cards should sit ~8px apart instead of the default 16px.
function isCompactCard(m: DisplayMessage): boolean {
  return m.role === 'subagent_result' || isToolOnlyAssistant(m)
}

// Tighten the gap between adjacent compact cards so that cross-message
// spacing (~8px) matches the within-message segment spacing.
// Parent uses gap-4 (16px); -mt-2 (-8px) bridges the difference.
const itemsWithFlags = computed(() =>
  items.value.map((m, i) => {
    const prev = i > 0 ? items.value[i - 1] : null
    const tighten = isCompactCard(m) && !!prev && isCompactCard(prev)
    return { message: m, tighten }
  }),
)

const isEmpty = computed(
  () => items.value.length === 0 && !chat.loadingHistory,
)

watch(
  () => chat.streamingMessage?.content,
  () => maintain(),
)
watch(
  () => chat.streamingMessage?.segments.length,
  () => maintain(),
)
watch(
  () => chat.autoResumeMessage?.content,
  () => maintain(),
)
watch(
  () => chat.autoResumeMessage?.segments.length,
  () => maintain(),
)
watch(
  () => chat.deferredMessages.length,
  () => maintain(),
)
watch(
  () => chat.messages.length,
  () => maintain(),
)
watch(
  () => chat.currentSessionId,
  () => scrollToBottom('auto'),
)
</script>

<template>
  <div class="relative h-full min-h-0">
    <div
      ref="containerRef"
      class="h-full overflow-y-auto bg-muted/30"
      role="log"
      aria-live="polite"
    >
      <div class="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-6">
        <template v-if="chat.loadingHistory">
          <div class="space-y-4">
            <Skeleton class="h-12 w-2/3" />
            <Skeleton class="h-20 w-full" />
            <Skeleton class="h-12 w-1/2 ml-auto" />
            <Skeleton class="h-24 w-full" />
          </div>
        </template>
        <template v-else-if="isEmpty">
          <EmptyState
            class="min-h-[60vh]"
            @suggest="(t) => composerBus.fill(t, { submit: true })"
          />
        </template>
        <template v-else>
          <template
            v-for="entry in itemsWithFlags"
            :key="entry.message.id"
          >
            <UserMessage
              v-if="entry.message.role === 'user'"
              :message="entry.message"
            />
            <SubagentResultCard
              v-else-if="entry.message.role === 'subagent_result'"
              :message="entry.message"
              :class="entry.tighten ? '-mt-2' : ''"
            />
            <AssistantMessage
              v-else
              :message="entry.message"
              :class="entry.tighten ? '-mt-2' : ''"
            />
          </template>
        </template>
      </div>
    </div>
    <Transition
      enter-active-class="transition duration-150"
      enter-from-class="opacity-0 translate-y-1"
      leave-active-class="transition duration-150"
      leave-to-class="opacity-0 translate-y-1"
    >
      <div
        v-if="!pinnedToBottom && items.length > 0"
        class="pointer-events-none absolute bottom-3 left-0 right-0 flex justify-center"
      >
        <div class="pointer-events-auto">
          <ScrollToBottom @click="scrollToBottom('smooth')" />
        </div>
      </div>
    </Transition>
  </div>
</template>

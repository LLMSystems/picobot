<script setup lang="ts">
import { computed, watch } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useAutoScroll } from '@/composables/useAutoScroll'
import UserMessage from './UserMessage.vue'
import AssistantMessage from './AssistantMessage.vue'
import EmptyState from './EmptyState.vue'
import ScrollToBottom from '@/components/common/ScrollToBottom.vue'
import { Skeleton } from '@/components/ui/skeleton'
import { useComposerBus } from '@/composables/useComposerBus'

const chat = useChatStore()
const { containerRef, pinnedToBottom, scrollToBottom, maintain } =
  useAutoScroll(80)
const composerBus = useComposerBus()

const items = computed(() => {
  const base = chat.messages
  return chat.streamingMessage ? [...base, chat.streamingMessage] : base
})

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
      <div class="mx-auto flex w-full max-w-3xl flex-col gap-5 px-4 py-6">
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
          <template v-for="m in items" :key="m.id">
            <UserMessage v-if="m.role === 'user'" :message="m" />
            <AssistantMessage v-else :message="m" />
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

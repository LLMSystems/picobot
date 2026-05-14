<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { Send, Square } from 'lucide-vue-next'
import { useChatStore } from '@/stores/chat'
import { useComposerBus } from '@/composables/useComposerBus'
import { toast } from 'vue-sonner'

const chat = useChatStore()
const bus = useComposerBus()

const text = ref('')
const isComposing = ref(false)
const textareaRef = ref<HTMLTextAreaElement | null>(null)

const canSend = computed(
  () =>
    text.value.trim().length > 0 &&
    !chat.isStreaming &&
    chat.currentSessionId !== null,
)

const placeholder = computed(() =>
  chat.currentSessionId ? '輸入訊息...（Enter 送出，Shift+Enter 換行）' : '請先選擇或建立對話',
)

function autoResize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  const next = Math.min(el.scrollHeight, 240)
  el.style.height = `${next}px`
}

watch(text, () => {
  void nextTick().then(autoResize)
})

watch(
  () => bus.focusToken.value,
  async () => {
    const fill = bus.consume()
    if (fill !== null) text.value = fill
    await nextTick()
    textareaRef.value?.focus()
    autoResize()
  },
)

async function send() {
  if (!canSend.value) return
  const t = text.value
  text.value = ''
  await nextTick()
  autoResize()
  try {
    await chat.send(t)
  } catch (err) {
    if (err instanceof Error) {
      toast.error('傳送失敗', {
        description: err.message,
      })
    }
  }
}

function onKeydown(e: KeyboardEvent) {
  if (isComposing.value || e.keyCode === 229) return
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    if (chat.isStreaming) return
    void send()
    return
  }
  if (e.key === 'Escape') {
    if (chat.isStreaming) {
      chat.stop()
    } else if (text.value) {
      text.value = ''
    }
    return
  }
  if (e.key === 'ArrowUp' && text.value === '') {
    const last = chat.retryLastUser()
    if (last) {
      e.preventDefault()
      text.value = last
    }
  }
}

function stop() {
  chat.stop()
}
</script>

<template>
  <div class="border-t bg-background">
    <div class="mx-auto w-full max-w-3xl px-4 py-3">
      <div
        class="relative rounded-2xl border bg-background px-3 py-2.5 pr-14 shadow-sm focus-within:ring-2 focus-within:ring-ring/40"
      >
        <textarea
          ref="textareaRef"
          v-model="text"
          rows="1"
          :placeholder="placeholder"
          :disabled="chat.currentSessionId === null"
          class="block max-h-60 min-h-[1.5rem] w-full resize-none bg-transparent text-sm leading-6 outline-none placeholder:text-muted-foreground"
          @keydown="onKeydown"
          @compositionstart="isComposing = true"
          @compositionend="isComposing = false"
          @input="autoResize"
        />
        <Button
          v-if="!chat.isStreaming"
          size="icon"
          variant="outline"
          class="absolute bottom-1 right-1.5 size-9 rounded-xl"
          :disabled="!canSend"
          aria-label="送出"
          @click="send"
        >
          <Send class="size-4" :class="canSend ? 'text-brand' : ''" />
        </Button>
        <Button
          v-else
          size="icon"
          variant="destructive"
          class="absolute bottom-1 right-1.5 size-9 rounded-xl"
          aria-label="停止"
          @click="stop"
        >
          <Square class="size-4" />
        </Button>
      </div>
      <p class="mt-1.5 text-center text-[11px] text-muted-foreground">
        AI 可能會產生錯誤資訊。重要資訊請自行驗證。
      </p>
    </div>
  </div>
</template>

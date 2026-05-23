<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { Send, Square, Plus, X, Loader2, AlertTriangle } from 'lucide-vue-next'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useChatStore } from '@/stores/chat'
import { useCapabilitiesStore } from '@/stores/capabilities'
import { useComposerBus } from '@/composables/useComposerBus'
import { useImageAttachments } from '@/composables/useImageAttachments'
import { useSelectedModel } from '@/composables/useSelectedModel'
import ModelSelector from './ModelSelector.vue'
import { ApiError } from '@/lib/errors'
import { toast } from 'vue-sonner'

const chat = useChatStore()
const caps = useCapabilitiesStore()
const bus = useComposerBus()

const text = ref('')
const isComposing = ref(false)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const isDragOver = ref(false)
let dragCounter = 0

const imagesEnabled = computed(
  () =>
    caps.data.features.multimodal && caps.data.features.session_workspace,
)

const attachments = useImageAttachments(() => chat.currentSessionId)
const { selected: selectedModel, resetToDefault: resetModel } =
  useSelectedModel()

const canSend = computed(() => {
  if (chat.isStreaming || chat.currentSessionId === null) return false
  if (attachments.hasUploading.value) return false
  const hasText = text.value.trim().length > 0
  return hasText || attachments.hasReady.value
})

const placeholder = computed(() =>
  chat.currentSessionId
    ? '問 Picobot 一個問題，或請它操作 workspace…'
    : '請先選擇或建立對話',
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
    const { text: filled, submit } = bus.consume()
    if (filled !== null) text.value = filled
    await nextTick()
    textareaRef.value?.focus()
    autoResize()
    if (submit && filled !== null && canSend.value) {
      void send()
    }
  },
  { immediate: true },
)

async function send() {
  if (!canSend.value) return
  const t = text.value
  const imgs = attachments.toImages()
  const model = selectedModel.value
  text.value = ''
  attachments.clearAll()
  await nextTick()
  autoResize()
  try {
    await chat.send(t, imgs, model)
  } catch (err) {
    if (err instanceof ApiError && err.code === 'MODEL_NOT_ALLOWED') {
      toast.error('所選模型不在允許清單', {
        description: '已重設為預設模型，請再試一次',
      })
      resetModel()
      void caps.refresh()
      return
    }
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

function openPicker() {
  if (!imagesEnabled.value) return
  fileInputRef.value?.click()
}

function onFilesChosen(e: Event) {
  const input = e.target as HTMLInputElement
  const list = input.files ? Array.from(input.files) : []
  if (list.length > 0) attachments.addFiles(list)
  input.value = ''
}

function onPaste(e: ClipboardEvent) {
  if (!imagesEnabled.value) return
  attachments.handlePaste(e)
}

function onDragEnter(e: DragEvent) {
  if (!imagesEnabled.value) return
  if (!e.dataTransfer?.types.includes('Files')) return
  dragCounter += 1
  isDragOver.value = true
}

function onDragLeave() {
  if (!imagesEnabled.value) return
  dragCounter = Math.max(0, dragCounter - 1)
  if (dragCounter === 0) isDragOver.value = false
}

function onDragOver(e: DragEvent) {
  if (!imagesEnabled.value) return
  if (e.dataTransfer?.types.includes('Files')) {
    e.preventDefault()
  }
}

function onDrop(e: DragEvent) {
  dragCounter = 0
  isDragOver.value = false
  if (!imagesEnabled.value) return
  attachments.handleDrop(e)
}
</script>

<template>
  <div class="bg-muted/30 pb-3 pt-3">
    <div class="mx-auto w-full max-w-3xl px-4">
      <div
        class="relative rounded-2xl border bg-background px-4 py-3 shadow-md transition-shadow focus-within:border-brand/40 focus-within:shadow-lg focus-within:ring-2 focus-within:ring-brand/20"
        :class="
          isDragOver
            ? 'border-brand/60 ring-2 ring-brand/30'
            : ''
        "
        @dragenter="onDragEnter"
        @dragleave="onDragLeave"
        @dragover="onDragOver"
        @drop="onDrop"
      >
        <div
          v-if="attachments.attachments.value.length > 0"
          class="mb-2 flex flex-wrap gap-2"
        >
          <div
            v-for="att in attachments.attachments.value"
            :key="att.id"
            class="group relative size-20 overflow-hidden rounded-lg border bg-muted"
          >
            <img
              :src="att.previewUrl"
              :alt="att.file.name"
              class="size-full object-cover"
              :class="att.status !== 'ready' ? 'opacity-50' : ''"
            />
            <div
              v-if="att.status === 'uploading'"
              class="absolute inset-0 flex items-center justify-center bg-black/30"
            >
              <Loader2 class="size-5 animate-spin text-white" />
            </div>
            <button
              v-if="att.status === 'error'"
              type="button"
              class="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-destructive/70 text-[10px] text-white"
              :title="att.error || '上傳失敗，點擊重試'"
              @click="attachments.retry(att.id)"
            >
              <AlertTriangle class="size-4" />
              <span>重試</span>
            </button>
            <button
              type="button"
              class="absolute right-1 top-1 grid size-5 place-items-center rounded-full bg-black/70 text-white opacity-0 transition-opacity hover:bg-black group-hover:opacity-100"
              aria-label="移除"
              @click.stop="attachments.remove(att.id)"
            >
              <X class="size-3" />
            </button>
          </div>
        </div>

        <textarea
          ref="textareaRef"
          v-model="text"
          rows="1"
          :placeholder="placeholder"
          :disabled="chat.currentSessionId === null"
          class="block max-h-60 min-h-[1.75rem] w-full resize-none bg-transparent text-sm leading-7 outline-none placeholder:text-muted-foreground"
          @keydown="onKeydown"
          @paste="onPaste"
          @compositionstart="isComposing = true"
          @compositionend="isComposing = false"
          @input="autoResize"
        />

        <div class="mt-1 flex items-center gap-1">
          <TooltipProvider v-if="imagesEnabled" :delay-duration="200">
            <Tooltip>
              <TooltipTrigger as-child>
                <Button
                  variant="ghost"
                  size="icon"
                  class="size-8 rounded-full"
                  :disabled="
                    chat.currentSessionId === null ||
                    !attachments.canAddMore.value
                  "
                  aria-label="附加圖片"
                  @click="openPicker"
                >
                  <Plus class="size-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top">
                附加圖片（拖曳 / 貼上 / 點擊）
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <input
            v-if="imagesEnabled"
            ref="fileInputRef"
            type="file"
            accept="image/*"
            multiple
            class="hidden"
            @change="onFilesChosen"
          />
          <ModelSelector />
          <div class="flex-1" />
          <Button
            v-if="!chat.isStreaming"
            size="icon"
            class="size-9 rounded-full bg-brand text-brand-foreground shadow-sm transition-transform hover:bg-brand/90 hover:scale-105 disabled:bg-muted disabled:text-muted-foreground disabled:shadow-none disabled:hover:scale-100"
            :disabled="!canSend"
            aria-label="送出"
            @click="send"
          >
            <Send class="size-4" />
          </Button>
          <Button
            v-else
            size="icon"
            variant="destructive"
            class="size-9 rounded-full shadow-sm"
            aria-label="停止"
            @click="stop"
          >
            <Square class="size-4" />
          </Button>
        </div>

        <div
          v-if="isDragOver"
          class="pointer-events-none absolute inset-0 flex items-center justify-center rounded-2xl border-2 border-dashed border-brand/60 bg-background/80 text-sm font-medium text-brand"
        >
          放開以附加圖片
        </div>
      </div>
      <p class="mt-2 text-center text-[11px] text-muted-foreground/70">
        Enter 送出・Shift+Enter 換行・拖曳 / 貼上 / 點 + 可附加圖片
      </p>
    </div>
  </div>
</template>

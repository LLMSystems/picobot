<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { Button } from '@/components/ui/button'
import { Copy, Pencil } from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import { api } from '@/lib/api'
import { useChatStore } from '@/stores/chat'
import type { DisplayMessage, DisplayMessageImage } from '@/lib/types'

const props = defineProps<{ message: DisplayMessage }>()

const chat = useChatStore()
const previewSrc = ref<string | null>(null)

const editing = ref(false)
const draft = ref('')
const textareaRef = ref<HTMLTextAreaElement | null>(null)

const canEdit = computed(
  () => !chat.isStreaming && props.message.status === 'complete',
)

function imageSrc(img: DisplayMessageImage): string | null {
  if (img.url) return img.url
  if (img.path && chat.currentSessionId) {
    return api.workspaceFileRawUrl(chat.currentSessionId, img.path)
  }
  return null
}

const visibleImages = computed(() =>
  (props.message.images ?? [])
    .map((img) => ({ img, src: imageSrc(img) }))
    .filter((x): x is { img: DisplayMessageImage; src: string } => !!x.src),
)

async function copy() {
  try {
    await navigator.clipboard.writeText(props.message.content)
    toast.success('已複製')
  } catch {
    toast.error('複製失敗')
  }
}

async function startEdit() {
  if (!canEdit.value) return
  draft.value = props.message.content
  editing.value = true
  await nextTick()
  const el = textareaRef.value
  if (el) {
    el.focus()
    el.setSelectionRange(el.value.length, el.value.length)
    autoResize()
  }
}

function cancelEdit() {
  editing.value = false
  draft.value = ''
}

async function submitEdit() {
  const next = draft.value.trim()
  if (!next || next === props.message.content) {
    cancelEdit()
    return
  }
  editing.value = false
  try {
    await chat.editAndResend(props.message.id, draft.value)
  } catch (err) {
    if (err instanceof Error) {
      toast.error('重新傳送失敗', { description: err.message })
    }
  }
}

function autoResize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 320)}px`
}

function onEditKeydown(e: KeyboardEvent) {
  if (e.isComposing) return
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    void submitEdit()
  } else if (e.key === 'Escape') {
    e.preventDefault()
    cancelEdit()
  }
}
</script>

<template>
  <div class="group flex justify-end">
    <div class="flex w-full max-w-[80%] flex-col items-end gap-1">
      <div
        v-if="visibleImages.length > 0"
        class="flex flex-wrap justify-end gap-1.5"
      >
        <button
          v-for="(item, idx) in visibleImages"
          :key="idx"
          type="button"
          class="overflow-hidden rounded-lg border bg-muted transition hover:opacity-90"
          @click="previewSrc = item.src"
        >
          <img
            :src="item.src"
            alt="attachment"
            class="max-h-48 max-w-[180px] object-cover"
          />
        </button>
      </div>

      <template v-if="editing">
        <div
          class="flex w-full flex-col gap-2 rounded-2xl border bg-muted px-3 py-2"
        >
          <textarea
            ref="textareaRef"
            v-model="draft"
            rows="1"
            class="max-h-80 min-h-[1.75rem] w-full resize-none bg-transparent text-sm leading-7 outline-none"
            @input="autoResize"
            @keydown="onEditKeydown"
          />
          <div class="flex items-center justify-end gap-1.5">
            <Button
              variant="ghost"
              size="sm"
              class="h-7 px-2 text-xs"
              @click="cancelEdit"
            >
              取消
            </Button>
            <Button
              size="sm"
              class="h-7 px-3 text-xs"
              :disabled="!draft.trim()"
              @click="submitEdit"
            >
              重新傳送
            </Button>
          </div>
        </div>
      </template>
      <template v-else>
        <div
          v-if="message.content"
          class="whitespace-pre-wrap break-words rounded-2xl rounded-br-md border bg-muted px-4 py-2 text-sm text-foreground"
        >
          {{ message.content }}
        </div>
        <div
          class="flex items-center gap-1 opacity-0 transition group-hover:opacity-100"
        >
          <Button
            v-if="canEdit"
            variant="ghost"
            size="icon"
            class="size-7"
            aria-label="編輯"
            title="編輯並重新傳送"
            @click="startEdit"
          >
            <Pencil class="size-3.5" />
          </Button>
          <Button
            v-if="message.content"
            variant="ghost"
            size="icon"
            class="size-7"
            aria-label="複製"
            @click="copy"
          >
            <Copy class="size-3.5" />
          </Button>
        </div>
      </template>
    </div>

    <div
      v-if="previewSrc"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-6"
      @click="previewSrc = null"
    >
      <img
        :src="previewSrc"
        alt="preview"
        class="max-h-full max-w-full cursor-zoom-out object-contain"
      />
    </div>
  </div>
</template>

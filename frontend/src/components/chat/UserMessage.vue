<script setup lang="ts">
import { computed, ref } from 'vue'
import { Button } from '@/components/ui/button'
import { Copy } from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import { api } from '@/lib/api'
import { useChatStore } from '@/stores/chat'
import type { DisplayMessage, DisplayMessageImage } from '@/lib/types'

const props = defineProps<{ message: DisplayMessage }>()

const chat = useChatStore()
const previewSrc = ref<string | null>(null)

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
</script>

<template>
  <div class="group flex justify-end">
    <div class="flex max-w-[80%] flex-col items-end gap-1">
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
      <div
        v-if="message.content"
        class="whitespace-pre-wrap break-words rounded-2xl rounded-br-md border bg-muted px-4 py-2 text-sm text-foreground"
      >
        {{ message.content }}
      </div>
      <div
        v-if="message.content"
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

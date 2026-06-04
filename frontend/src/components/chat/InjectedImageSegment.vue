<script setup lang="ts">
import { computed, ref } from 'vue'
import { Image as ImageIcon } from 'lucide-vue-next'
import { api } from '@/lib/api'
import type { DisplayMessageImage } from '@/lib/types'

const props = defineProps<{
  images: DisplayMessageImage[]
  sessionId: string
}>()

const previewSrc = ref<string | null>(null)

function imageSrc(img: DisplayMessageImage): string | null {
  if (img.url) return img.url
  if (img.path && props.sessionId) {
    return api.workspaceFileRawUrl(props.sessionId, img.path)
  }
  return null
}

const visibleImages = computed(() =>
  (props.images ?? [])
    .map((img) => ({ img, src: imageSrc(img) }))
    .filter((x): x is { img: DisplayMessageImage; src: string } => !!x.src),
)
</script>

<template>
  <div v-if="visibleImages.length > 0" class="flex flex-col items-start gap-1.5">
    <div class="flex items-center gap-1.5 text-xs text-muted-foreground">
      <ImageIcon class="size-3.5" />
      <span>由 view_image 載入</span>
    </div>
    <div class="flex flex-wrap justify-start gap-1.5">
      <button
        v-for="(item, idx) in visibleImages"
        :key="idx"
        type="button"
        class="overflow-hidden rounded-lg border bg-muted transition hover:opacity-90"
        @click="previewSrc = item.src"
      >
        <img
          :src="item.src"
          alt="view_image attachment"
          class="max-h-48 max-w-[180px] object-cover"
        />
      </button>
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

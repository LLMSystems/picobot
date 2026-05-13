<script setup lang="ts">
import { Button } from '@/components/ui/button'
import { Copy } from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import type { DisplayMessage } from '@/lib/types'

const props = defineProps<{ message: DisplayMessage }>()

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
        class="whitespace-pre-wrap break-words rounded-2xl rounded-br-md border bg-muted px-4 py-2 text-sm text-foreground"
      >
        {{ message.content }}
      </div>
      <div
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

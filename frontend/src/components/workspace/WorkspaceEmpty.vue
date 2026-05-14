<script setup lang="ts">
import { FolderOpen, FolderX, AlertTriangle } from 'lucide-vue-next'
defineProps<{ variant: 'empty' | 'unavailable' | 'error' }>()
</script>

<template>
  <div class="flex flex-1 flex-col items-center justify-center gap-2 px-4 text-center text-xs text-muted-foreground">
    <template v-if="variant === 'empty'">
      <FolderOpen class="size-7 opacity-40" />
      <p>Workspace 為空</p>
      <p class="opacity-70">拖檔案進來，或等 agent 開始建立檔案</p>
    </template>
    <template v-else-if="variant === 'unavailable'">
      <FolderX class="size-7 opacity-40" />
      <p>此 session 沒有 workspace</p>
    </template>
    <template v-else>
      <AlertTriangle class="size-7 opacity-40" />
      <p>無法讀取 workspace</p>
    </template>
  </div>
</template>

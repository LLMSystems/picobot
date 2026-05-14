<script setup lang="ts">
import picoagentLogo from '@/assets/picoagent.png'

defineEmits<{ (e: 'suggest', text: string): void }>()

const suggestions = [
  '介紹一下你自己',
  '列出目前 workspace 的檔案結構',
  '幫我寫一個簡單的 Python script',
  '幫我彙整近期台積電新聞',
]
</script>

<template>
  <div
    class="flex h-full flex-col items-center justify-center gap-6 px-6 text-center"
  >
    <div class="space-y-3">
      <img
        :src="picoagentLogo"
        alt="Picobot"
        class="mx-auto size-50 select-none object-contain"
        draggable="false"
      />
      <h2 class="text-xl font-semibold">你好，我是 Picobot</h2>
      <p class="text-sm text-muted-foreground">
        試試以下提示，或直接在下方輸入訊息
      </p>
    </div>
    <div class="grid w-full max-w-xl grid-cols-1 gap-2 sm:grid-cols-2">
      <button
        v-for="s in suggestions"
        :key="s"
        class="rounded-lg border bg-card px-3 py-2.5 text-left text-sm transition hover:bg-muted"
        @click="$emit('suggest', s)"
      >
        {{ s }}
      </button>
    </div>
  </div>
</template>

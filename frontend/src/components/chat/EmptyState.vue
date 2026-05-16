<script setup lang="ts">
import { Sparkles, FolderTree, Code2, Newspaper } from 'lucide-vue-next'
import picoagentLogo from '@/assets/picoagent.png'

defineEmits<{ (e: 'suggest', text: string): void }>()

interface Command {
  icon: typeof Sparkles
  title: string
  description: string
  prompt: string
}

const commands: Command[] = [
  {
    icon: Sparkles,
    title: '介紹一下你自己',
    description: '了解 Picobot 可以做什麼',
    prompt: '介紹一下你自己',
  },
  {
    icon: FolderTree,
    title: '列出 workspace 檔案',
    description: '快速查看目前專案結構',
    prompt: '列出目前 workspace 的檔案結構',
  },
  {
    icon: Code2,
    title: '產生 Python script',
    description: '建立一個簡單可執行的程式',
    prompt: '幫我寫一個簡單的 Python script',
  },
  {
    icon: Newspaper,
    title: '搜尋近期新聞',
    description: '整理最新資訊與來源',
    prompt: '幫我彙整近期台積電新聞',
  },
]
</script>

<template>
  <div
    class="relative flex h-full flex-col items-center justify-center gap-10 px-6 py-10 text-center"
  >
    <div
      aria-hidden="true"
      class="pointer-events-none absolute inset-x-0 top-0 -z-10 h-72 bg-gradient-to-b from-brand/10 via-brand/5 to-transparent blur-2xl"
    />

    <div class="flex max-w-xl flex-col items-center gap-4">
      <img
        :src="picoagentLogo"
        alt="Picobot"
        class="size-40 select-none object-contain drop-shadow-sm"
        draggable="false"
      />
      <div class="space-y-2">
        <h1 class="text-3xl font-semibold tracking-tight">
          你好，我是 Picobot
        </h1>
        <p class="text-base font-medium text-brand">
          你的輕量 Workspace Agent
        </p>
        <p class="text-sm leading-relaxed text-muted-foreground">
          我可以幫你讀取檔案、撰寫程式、搜尋資訊，或整理目前 workspace。
        </p>
      </div>
    </div>

    <div class="grid w-full max-w-2xl grid-cols-1 gap-3 sm:grid-cols-2">
      <button
        v-for="c in commands"
        :key="c.title"
        class="group flex items-start gap-3 rounded-xl border bg-card p-4 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:border-brand/40 hover:bg-brand/5 hover:shadow-md"
        @click="$emit('suggest', c.prompt)"
      >
        <span
          class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand/10 text-brand transition-colors group-hover:bg-brand/20"
        >
          <component :is="c.icon" class="size-4.5" />
        </span>
        <span class="min-w-0 flex-1">
          <span class="block text-sm font-medium leading-tight">
            {{ c.title }}
          </span>
          <span class="mt-1 block text-xs leading-relaxed text-muted-foreground">
            {{ c.description }}
          </span>
        </span>
      </button>
    </div>
  </div>
</template>

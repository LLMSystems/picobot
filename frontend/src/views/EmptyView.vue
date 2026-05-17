<script setup lang="ts">
import { nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { useSessionsStore } from '@/stores/sessions'
import { useComposerBus } from '@/composables/useComposerBus'
import {
  Plus,
  Sparkles,
  FolderTree,
  Code2,
  Newspaper,
} from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import picoagentLogo from '@/assets/picoagent.png'

const router = useRouter()
const sessions = useSessionsStore()
const composerBus = useComposerBus()

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
    prompt: '幫我寫一個簡單的快速排序 Python script，並存成檔案',
  },
  {
    icon: Newspaper,
    title: '搜尋近期新聞',
    description: '整理最新資訊與來源',
    prompt: '幫我彙整近期台積電新聞',
  },
]

async function createSession(): Promise<string | null> {
  try {
    const s = await sessions.create()
    return s.session_id
  } catch (err) {
    toast.error('建立對話失敗', {
      description: err instanceof Error ? err.message : '',
    })
    return null
  }
}

async function createAndGo() {
  const id = await createSession()
  if (id) router.push(`/c/${id}`)
}

async function startWith(prompt: string) {
  const id = await createSession()
  if (!id) return
  await router.push(`/c/${id}`)
  await nextTick()
  composerBus.fill(prompt, { submit: true })
}
</script>

<template>
  <div
    class="relative flex h-full w-full flex-col items-center px-6 pb-20 pt-[7vh] text-center sm:pt-[9vh]"
  >
    <div
      aria-hidden="true"
      class="pointer-events-none absolute inset-x-0 top-0 -z-10 h-80 bg-gradient-to-b from-brand/10 via-brand/5 to-transparent blur-2xl"
    />

    <div class="flex max-w-xl flex-col items-center gap-5">
      <img
        :src="picoagentLogo"
        alt="Picobot"
        class="size-40 select-none object-contain drop-shadow-sm"
        draggable="false"
      />
      <div class="space-y-2.5">
        <h1 class="text-3xl font-semibold tracking-tight">
          歡迎使用 Picobot
        </h1>
        <p class="text-base font-medium text-brand">
          你的輕量 Workspace Agent
        </p>
        <p class="text-sm leading-relaxed text-muted-foreground">
          我可以幫你讀取檔案、撰寫程式、搜尋資訊，或整理目前 workspace。
        </p>
      </div>
      <Button
        class="h-10 gap-1.5 rounded-xl bg-brand px-5 text-sm font-medium text-brand-foreground shadow-none transition-shadow hover:bg-brand/90 hover:shadow-md"
        @click="createAndGo"
      >
        <Plus class="size-4" />
        開始新對話
      </Button>
    </div>

    <div class="mt-16 grid w-full max-w-2xl grid-cols-1 gap-3 sm:mt-20 sm:grid-cols-2">
      <button
        v-for="c in commands"
        :key="c.title"
        class="group flex items-start gap-3 rounded-xl border bg-card p-4 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:border-brand/40 hover:bg-brand/5 hover:shadow-md"
        @click="startWith(c.prompt)"
      >
        <span
          class="flex size-10 shrink-0 items-center justify-center rounded-xl bg-indigo-50 text-indigo-500 transition-colors group-hover:bg-indigo-100 dark:bg-brand/15 dark:text-brand dark:group-hover:bg-brand/25"
        >
          <component :is="c.icon" class="size-5" />
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

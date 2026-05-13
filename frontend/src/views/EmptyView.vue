<script setup lang="ts">
import { useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { useSessionsStore } from '@/stores/sessions'
import { MessageSquarePlus } from 'lucide-vue-next'
import { toast } from 'vue-sonner'

const router = useRouter()
const sessions = useSessionsStore()

async function createAndGo() {
  try {
    const s = await sessions.create()
    router.push(`/c/${s.session_id}`)
  } catch (err) {
    toast.error('建立對話失敗', {
      description: err instanceof Error ? err.message : '',
    })
  }
}
</script>

<template>
  <div
    class="flex h-full w-full flex-col items-center justify-center gap-6 px-6 text-center"
  >
    <div class="space-y-2">
      <h1 class="text-2xl font-semibold tracking-tight">歡迎使用 picobot</h1>
      <p class="text-sm text-muted-foreground">
        從左側選擇一個對話，或建立新的對話開始
      </p>
    </div>
    <Button class="gap-2" @click="createAndGo">
      <MessageSquarePlus class="size-4" />
      開始新對話
    </Button>
  </div>
</template>

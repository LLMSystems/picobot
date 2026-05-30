<script setup lang="ts">
// Two-icon mode switcher (Chat vs Dashboard). Rendered in both shells'
// top bars so users can hop between the two modes from anywhere.
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MessagesSquare, LayoutDashboard } from 'lucide-vue-next'
import { useSessionsStore } from '@/stores/sessions'

const route = useRoute()
const router = useRouter()
const sessions = useSessionsStore()

const isDashboard = computed(() => route.meta.shell === 'dashboard')
const isChat = computed(() => route.meta.shell === 'app')

function goChat() {
  if (isChat.value) return
  // Land on the most recent session, or the empty view if none exist.
  const target = sessions.list[0]
  if (target) router.push(`/c/${target.session_id}`)
  else router.push('/')
}

function goDashboard() {
  if (isDashboard.value) return
  router.push('/dashboard')
}
</script>

<template>
  <div class="inline-flex items-center gap-1 rounded-md border bg-background p-0.5">
    <button
      type="button"
      class="inline-flex h-7 items-center gap-1.5 rounded-[5px] px-2 text-xs font-medium transition-colors"
      :class="isChat
        ? 'bg-muted text-foreground'
        : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground'"
      @click="goChat"
    >
      <MessagesSquare class="size-3.5" />
      <span>聊天</span>
    </button>
    <button
      type="button"
      class="inline-flex h-7 items-center gap-1.5 rounded-[5px] px-2 text-xs font-medium transition-colors"
      :class="isDashboard
        ? 'bg-muted text-foreground'
        : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground'"
      @click="goDashboard"
    >
      <LayoutDashboard class="size-3.5" />
      <span>Dashboard</span>
    </button>
  </div>
</template>

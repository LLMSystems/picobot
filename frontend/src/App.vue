<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppShell from '@/components/layout/AppShell.vue'
import DashboardShell from '@/components/layout/DashboardShell.vue'
import { Toaster } from '@/components/ui/sonner'
import { useCapabilitiesStore } from '@/stores/capabilities'
import { useAgentTypesStore } from '@/stores/agentTypes'
import { useSessionsStore } from '@/stores/sessions'
import { useChatStore } from '@/stores/chat'
import { useAuthStore } from '@/stores/auth'
import { useSkillsStore } from '@/stores/skills'
import { useMcpStore } from '@/stores/mcp'
import { useTheme } from '@/composables/useTheme'
import { useGlobalShortcuts } from '@/composables/useShortcuts'
import { useComposerBus } from '@/composables/useComposerBus'
import { useWorkspaceStore } from '@/stores/workspace'
import { onUnauthorized } from '@/lib/api'
import { toast } from 'vue-sonner'

const caps = useCapabilitiesStore()
const agentTypes = useAgentTypesStore()
const sessions = useSessionsStore()
const chat = useChatStore()
const auth = useAuthStore()
const skills = useSkillsStore()
const mcp = useMcpStore()
const router = useRouter()
const route = useRoute()
const bus = useComposerBus()
const ws = useWorkspaceStore()

useTheme()

const shell = computed(() => {
  if (route.meta.shell === 'auth') return 'auth'
  if (route.meta.shell === 'dashboard') return 'dashboard'
  return 'app'
})

// A 401 from any call means the cookie is gone/expired — drop local state and
// send the user to login (preserving where they were).
onUnauthorized(() => {
  auth.reset()
  if (route.meta.public !== true) {
    void router.replace({
      name: 'login',
      query: route.fullPath !== '/' ? { redirect: route.fullPath } : undefined,
    })
  }
})

// Load app data only once authenticated; re-runs after login. The router guard
// resolves auth before the first navigation, so this fires on initial load too.
watch(
  () => auth.user?.id ?? null,
  async (id, prevId) => {
    // On any user switch (incl. logout), drop caches that lazy-load and would
    // otherwise survive into the next user's session within the same page.
    if (id !== prevId) {
      skills.reset()
      mcp.reset()
    }
    if (!auth.isAuthenticated) return
    await Promise.all([caps.load(), sessions.fetchAll()])
    if (caps.failed) {
      toast.warning('能力資訊載入失敗，已使用預設值')
    }
    if (caps.data.features.agent_types) {
      void agentTypes.load()
    }
    if (route.name === 'empty' && sessions.list[0]) {
      router.replace(`/c/${sessions.list[0].session_id}`)
    }
  },
  { immediate: true },
)

async function newChatShortcut() {
  try {
    const s = await sessions.create()
    router.push(`/c/${s.session_id}`)
  } catch (err) {
    toast.error('建立對話失敗', {
      description: err instanceof Error ? err.message : '',
    })
  }
}

function deleteCurrent() {
  const id = chat.currentSessionId
  if (!id) return
  const s = sessions.findById(id)
  if (!s) return
  if (!confirm(`確定刪除「${s.title}」？此操作無法復原。`)) return
  if (chat.isStreaming) chat.stop()
  void sessions
    .remove(id)
    .then(() => {
      const next = sessions.list[0]
      if (next) router.replace(`/c/${next.session_id}`)
      else router.replace('/')
    })
    .catch((err) => {
      toast.error('刪除失敗', {
        description: err instanceof Error ? err.message : '',
      })
    })
}

function gotoOffset(delta: number) {
  const list = sessions.list
  if (list.length === 0) return
  const cur = chat.currentSessionId
  let idx = list.findIndex((s) => s.session_id === cur)
  if (idx < 0) idx = -1
  idx = Math.max(0, Math.min(list.length - 1, idx + delta))
  const target = list[idx]
  if (target) router.push(`/c/${target.session_id}`)
}

useGlobalShortcuts({
  onNewChat: newChatShortcut,
  onDeleteCurrent: deleteCurrent,
  onFocusComposer: () => bus.focus(),
  onPrev: () => gotoOffset(-1),
  onNext: () => gotoOffset(1),
  onToggleWorkspace: () => ws.toggleVisible(),
})
</script>

<template>
  <RouterView v-if="shell === 'auth'" />
  <DashboardShell v-else-if="shell === 'dashboard'">
    <RouterView />
  </DashboardShell>
  <AppShell v-else>
    <RouterView />
  </AppShell>
  <Toaster rich-colors close-button position="top-center" />
</template>

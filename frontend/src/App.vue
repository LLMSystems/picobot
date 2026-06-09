<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppShell from '@/components/layout/AppShell.vue'
import DashboardShell from '@/components/layout/DashboardShell.vue'
import { Toaster } from '@/components/ui/sonner'
import { useCapabilitiesStore } from '@/stores/capabilities'
import { useAgentTypesStore } from '@/stores/agentTypes'
import { useSessionsStore } from '@/stores/sessions'
import { useChatStore } from '@/stores/chat'
import { useTheme } from '@/composables/useTheme'
import { useGlobalShortcuts } from '@/composables/useShortcuts'
import { useComposerBus } from '@/composables/useComposerBus'
import { useWorkspaceStore } from '@/stores/workspace'
import { toast } from 'vue-sonner'

const caps = useCapabilitiesStore()
const agentTypes = useAgentTypesStore()
const sessions = useSessionsStore()
const chat = useChatStore()
const router = useRouter()
const route = useRoute()
const bus = useComposerBus()
const ws = useWorkspaceStore()

useTheme()

const shell = computed(() =>
  route.meta.shell === 'dashboard' ? 'dashboard' : 'app',
)

onMounted(async () => {
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
})

watch(
  () => caps.failed,
  (failed) => {
    if (failed) {
      // already toasted above; nothing more to do
    }
  },
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
  <DashboardShell v-if="shell === 'dashboard'">
    <RouterView />
  </DashboardShell>
  <AppShell v-else>
    <RouterView />
  </AppShell>
  <Toaster rich-colors close-button position="top-center" />
</template>

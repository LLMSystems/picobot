<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Plus, MessageSquare, Search, X } from 'lucide-vue-next'
import { useSessionsStore } from '@/stores/sessions'
import { useChatStore } from '@/stores/chat'
import { useCapabilitiesStore } from '@/stores/capabilities'
import { toast } from 'vue-sonner'
import SessionItem from '@/components/sessions/SessionItem.vue'
import AgentTypeCards from '@/components/sessions/AgentTypeCards.vue'
import SidebarUserMenu from '@/components/layout/SidebarUserMenu.vue'
import { Skeleton } from '@/components/ui/skeleton'
import picoagentLogo from '@/assets/picobot_head.png'

const emit = defineEmits<{ (e: 'select'): void }>()

const sessions = useSessionsStore()
const chat = useChatStore()
const caps = useCapabilitiesStore()
const router = useRouter()
const route = useRoute()

const agentTypesEnabled = computed(() => caps.data.features.agent_types)
const pickerOpen = ref(false)
const creating = ref(false)

const currentId = computed(() =>
  route.name === 'chat' && typeof route.params.id === 'string'
    ? route.params.id
    : null,
)

const deleteTarget = ref<string | null>(null)
const deleteTitle = computed(() => {
  const s = deleteTarget.value ? sessions.findById(deleteTarget.value) : null
  return s?.title ?? ''
})

const search = ref('')

const filteredSessions = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return sessions.list
  return sessions.list.filter((s) => {
    if (s.title.toLowerCase().includes(q)) return true
    if (s.last_user_message?.toLowerCase().includes(q)) return true
    if (s.last_assistant_preview?.toLowerCase().includes(q)) return true
    return false
  })
})

async function newChat() {
  if (agentTypesEnabled.value) {
    pickerOpen.value = true
    return
  }
  await startCreate()
}

async function startCreate(agentType?: string) {
  if (creating.value) return
  creating.value = true
  try {
    const s = await sessions.create(agentType ? { agentType } : {})
    pickerOpen.value = false
    router.push(`/c/${s.session_id}`)
    emit('select')
  } catch (err) {
    toast.error('建立對話失敗', {
      description: err instanceof Error ? err.message : '',
    })
  } finally {
    creating.value = false
  }
}

function openChat(id: string) {
  if (chat.isStreaming) chat.stop()
  router.push(`/c/${id}`)
  emit('select')
}

async function renameSession(id: string, title: string) {
  try {
    await sessions.rename(id, title)
  } catch (err) {
    toast.error('改名失敗', {
      description: err instanceof Error ? err.message : '',
    })
  }
}

function askDelete(id: string) {
  deleteTarget.value = id
}

async function confirmDelete() {
  const id = deleteTarget.value
  if (!id) return
  deleteTarget.value = null
  const wasCurrent = currentId.value === id
  if (wasCurrent && chat.isStreaming) chat.stop()
  try {
    await sessions.remove(id)
    if (wasCurrent) {
      const next = sessions.list[0]
      if (next) router.replace(`/c/${next.session_id}`)
      else router.replace('/')
    }
  } catch (err) {
    toast.error('刪除失敗', {
      description: err instanceof Error ? err.message : '',
    })
  }
}
</script>

<template>
  <div class="flex h-full flex-col">
    <div class="flex items-center gap-2 px-3 py-3">
      <img
        :src="picoagentLogo"
        alt=""
        aria-hidden="true"
        class="size-10 -translate-y-0.5 select-none object-contain"
        draggable="false"
      />
      <span class="text-lg font-semibold tracking-tight">Picobot</span>
    </div>
    <div class="space-y-2 px-3 pb-3">
      <Button
        size="sm"
        class="h-8 w-full gap-1.5 rounded-[8px] bg-primary text-sm font-medium text-primary-foreground shadow-none transition-shadow hover:bg-primary/90 hover:shadow-md"
        @click="newChat"
      >
        <Plus class="size-3.5" />
        新對話
      </Button>
      <div class="relative">
        <Search
          class="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
        />
        <input
          v-model="search"
          type="text"
          placeholder="搜尋對話…"
          class="h-8 w-full rounded-[8px] border bg-background pl-7 pr-7 text-xs outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
        />
        <button
          v-if="search"
          type="button"
          class="absolute right-1.5 top-1/2 grid size-5 -translate-y-1/2 place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
          aria-label="清空搜尋"
          @click="search = ''"
        >
          <X class="size-3" />
        </button>
      </div>
    </div>

    <div class="flex-1 min-h-0 overflow-y-auto px-2 pb-3">
      <template v-if="!sessions.loaded && sessions.loading">
        <div class="space-y-2 px-1 py-2">
          <Skeleton v-for="i in 5" :key="i" class="h-12 w-full" />
        </div>
      </template>
      <template v-else-if="sessions.list.length === 0">
        <div class="px-3 py-8 text-center text-xs text-muted-foreground">
          <MessageSquare class="mx-auto mb-2 size-6 opacity-40" />
          <p>還沒有對話</p>
          <p class="mt-1">按上方「新對話」開始</p>
        </div>
      </template>
      <template v-else-if="filteredSessions.length === 0">
        <div class="px-3 py-8 text-center text-xs text-muted-foreground">
          <p>找不到符合「{{ search }}」的對話</p>
        </div>
      </template>
      <ul v-else role="listbox" class="space-y-0.5">
        <li v-for="s in filteredSessions" :key="s.session_id">
          <SessionItem
            :session="s"
            :active="currentId === s.session_id"
            @select="openChat(s.session_id)"
            @rename="(title) => renameSession(s.session_id, title)"
            @delete="askDelete(s.session_id)"
          />
        </li>
      </ul>
    </div>

    <SidebarUserMenu />

    <Dialog
      :open="pickerOpen"
      @update:open="(v) => (pickerOpen = v)"
    >
      <DialogContent class="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>選擇 Agent 類型</DialogTitle>
          <DialogDescription>
            不同類型的 Picobot 有各自的專長與工具，建立後無法更改。
          </DialogDescription>
        </DialogHeader>
        <AgentTypeCards :busy="creating" @select="startCreate" />
      </DialogContent>
    </Dialog>

    <Dialog
      :open="deleteTarget !== null"
      @update:open="(v) => !v && (deleteTarget = null)"
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>確定刪除這個對話？</DialogTitle>
          <DialogDescription>
            「{{ deleteTitle }}」將被永久刪除，此操作無法復原。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" @click="deleteTarget = null">取消</Button>
          <Button variant="destructive" @click="confirmDelete">刪除</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

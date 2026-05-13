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
import { Plus, MessageSquare } from 'lucide-vue-next'
import { useSessionsStore } from '@/stores/sessions'
import { useChatStore } from '@/stores/chat'
import { toast } from 'vue-sonner'
import SessionItem from '@/components/sessions/SessionItem.vue'
import { Skeleton } from '@/components/ui/skeleton'

const emit = defineEmits<{ (e: 'select'): void }>()

const sessions = useSessionsStore()
const chat = useChatStore()
const router = useRouter()
const route = useRoute()

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

async function newChat() {
  try {
    const s = await sessions.create()
    router.push(`/c/${s.session_id}`)
    emit('select')
  } catch (err) {
    toast.error('建立對話失敗', {
      description: err instanceof Error ? err.message : '',
    })
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
    <div class="flex items-center justify-between gap-2 px-3 py-3">
      <span class="text-lg font-semibold tracking-tight">Picobot</span>
      <Button size="sm" variant="outline" class="gap-1.5" @click="newChat">
        <Plus class="size-4" />
        新對話
      </Button>
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
      <ul v-else role="listbox" class="space-y-0.5">
        <li v-for="s in sessions.list" :key="s.session_id">
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

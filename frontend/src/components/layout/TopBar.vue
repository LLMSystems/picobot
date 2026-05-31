<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useSessionsStore } from '@/stores/sessions'
import { useCapabilitiesStore } from '@/stores/capabilities'
import { Button } from '@/components/ui/button'
import { Menu, Pencil, Moon, Sun, PanelRight, Bell, BellOff, Download, Settings } from 'lucide-vue-next'
import ModeSwitcher from '@/components/layout/ModeSwitcher.vue'
import AlertsBadge from '@/components/layout/AlertsBadge.vue'
import SettingsDialog from '@/components/settings/SettingsDialog.vue'
import { useSettingsStore } from '@/stores/settings'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { toast } from 'vue-sonner'
import { useTheme } from '@/composables/useTheme'
import { useWorkspaceStore } from '@/stores/workspace'
import { useNotifications } from '@/composables/useNotifications'
import { api } from '@/lib/api'
import {
  downloadAsFile,
  formatMessagesAsJson,
  formatMessagesAsMarkdown,
  sanitizeFilename,
} from '@/lib/export'

defineEmits<{ (e: 'toggle-sidebar'): void }>()

const route = useRoute()
const sessions = useSessionsStore()
const caps = useCapabilitiesStore()
const ws = useWorkspaceStore()
const settings = useSettingsStore()
const { theme, toggle: toggleTheme } = useTheme()
const notifs = useNotifications()

const exporting = ref(false)
const settingsOpen = ref(false)

async function exportSession(format: 'markdown' | 'json') {
  const sid = currentId.value
  const s = currentSession.value
  if (!sid || !s) return
  if (exporting.value) return
  exporting.value = true
  try {
    const { messages } = await api.getMessages(sid)
    const base = sanitizeFilename(s.title || 'picobot-session')
    if (format === 'markdown') {
      const content = formatMessagesAsMarkdown(messages, s.title, sid)
      downloadAsFile(`${base}.md`, content, 'text/markdown')
    } else {
      const content = formatMessagesAsJson(messages, s.title, sid)
      downloadAsFile(`${base}.json`, content, 'application/json')
    }
    toast.success('已匯出', { description: `${base}.${format === 'markdown' ? 'md' : 'json'}` })
  } catch (err) {
    toast.error('匯出失敗', {
      description: err instanceof Error ? err.message : '',
    })
  } finally {
    exporting.value = false
  }
}

async function toggleNotifications() {
  if (!notifs.supported) {
    toast.error('此瀏覽器不支援通知')
    return
  }
  const result = await notifs.toggle()
  if (notifs.permission.value === 'denied') {
    toast.error('通知權限已被瀏覽器拒絕', {
      description: '請在瀏覽器設定開啟此網站的通知權限',
    })
    return
  }
  if (result) {
    toast.success('已開啟通知', {
      description: '長任務完成時若分頁不在前景會通知你',
    })
  } else {
    toast.info('已關閉通知')
  }
}

const currentId = computed(() =>
  route.name === 'chat' && typeof route.params.id === 'string'
    ? route.params.id
    : null,
)

const currentSession = computed(() =>
  currentId.value ? sessions.findById(currentId.value) : undefined,
)

const title = computed(() => currentSession.value?.title ?? '')

const editing = ref(false)
const draft = ref('')
const inputRef = ref<HTMLInputElement | null>(null)

watch(currentId, () => {
  editing.value = false
})

async function startEdit() {
  if (!currentSession.value) return
  draft.value = currentSession.value.title
  editing.value = true
  await nextTick()
  inputRef.value?.focus()
  inputRef.value?.select()
}

async function commit() {
  if (!currentSession.value) {
    editing.value = false
    return
  }
  const id = currentSession.value.session_id
  const next = draft.value.trim()
  const prev = currentSession.value.title
  editing.value = false
  if (!next || next === prev) return
  try {
    await sessions.rename(id, next)
  } catch (err) {
    toast.error('改名失敗', {
      description: err instanceof Error ? err.message : '',
    })
  }
}

function cancel() {
  editing.value = false
}
</script>

<template>
  <header
    class="flex h-12 shrink-0 items-center gap-2 border-b bg-background px-3"
  >
    <Button
      variant="ghost"
      size="icon"
      class="md:hidden"
      aria-label="切換 Sidebar"
      @click="$emit('toggle-sidebar')"
    >
      <Menu class="size-4" />
    </Button>

    <div class="flex min-w-0 flex-1 items-center gap-2">
      <template v-if="currentSession">
        <input
          v-if="editing"
          ref="inputRef"
          v-model="draft"
          class="min-w-0 flex-1 rounded-md border bg-background px-2 py-1 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          @blur="commit"
          @keydown.enter.prevent="commit"
          @keydown.esc.prevent="cancel"
        />
        <button
          v-else
          class="group flex min-w-0 items-center gap-1 truncate rounded px-2 py-1 text-sm font-medium hover:bg-muted"
          :title="title"
          @dblclick="startEdit"
          @click="startEdit"
        >
          <span class="truncate">{{ title || 'New Chat' }}</span>
          <Pencil
            class="size-3 shrink-0 opacity-0 transition group-hover:opacity-60"
          />
        </button>
      </template>
      <span v-else class="text-sm text-muted-foreground">Picobot</span>
    </div>

    <div class="flex items-center gap-2 text-xs text-muted-foreground">
      <AlertsBadge />
      <ModeSwitcher />
      <DropdownMenu v-if="currentSession">
        <DropdownMenuTrigger as-child>
          <Button
            variant="ghost"
            size="icon"
            aria-label="匯出對話"
            title="匯出對話"
            :disabled="exporting"
          >
            <Download class="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" class="w-44">
          <DropdownMenuItem @click="exportSession('markdown')">
            <span class="text-sm">匯出為 Markdown</span>
          </DropdownMenuItem>
          <DropdownMenuItem @click="exportSession('json')">
            <span class="text-sm">匯出為 JSON</span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <Button
        v-if="notifs.supported"
        variant="ghost"
        size="icon"
        :aria-pressed="notifs.enabled.value"
        aria-label="切換通知"
        title="長任務完成通知"
        @click="toggleNotifications"
      >
        <Bell
          v-if="notifs.enabled.value && notifs.permission.value === 'granted'"
          class="size-4"
        />
        <BellOff v-else class="size-4 opacity-50" />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        aria-label="設定"
        title="設定"
        class="relative"
        @click="settingsOpen = true"
      >
        <Settings class="size-4" />
        <span
          v-if="settings.hasOverrides"
          class="absolute right-1.5 top-1.5 size-1.5 rounded-full bg-amber-500"
          aria-hidden="true"
        />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        aria-label="切換主題"
        @click="toggleTheme"
      >
        <Sun v-if="theme === 'dark'" class="size-4" />
        <Moon v-else class="size-4" />
      </Button>
      <Button
        v-if="caps.data.features.session_workspace"
        variant="ghost"
        size="icon"
        :aria-pressed="ws.visible"
        aria-label="切換 Workspace"
        title="切換 Workspace (Cmd/Ctrl+B)"
        @click="ws.toggleVisible()"
      >
        <PanelRight class="size-4" :class="ws.visible ? '' : 'opacity-50'" />
      </Button>
    </div>
  </header>

  <SettingsDialog v-model:open="settingsOpen" />
</template>

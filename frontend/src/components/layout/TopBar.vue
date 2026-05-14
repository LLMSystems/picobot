<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useSessionsStore } from '@/stores/sessions'
import { useCapabilitiesStore } from '@/stores/capabilities'
import { Button } from '@/components/ui/button'
import { Menu, Pencil, Moon, Sun, PanelRight } from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import { useTheme } from '@/composables/useTheme'
import { useWorkspaceStore } from '@/stores/workspace'

defineEmits<{ (e: 'toggle-sidebar'): void }>()

const route = useRoute()
const sessions = useSessionsStore()
const caps = useCapabilitiesStore()
const ws = useWorkspaceStore()
const { theme, toggle: toggleTheme } = useTheme()

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
      <span class="hidden rounded-full border px-2 py-0.5 sm:inline">
        {{ caps.modelName }}
      </span>
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
</template>

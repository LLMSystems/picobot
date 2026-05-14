<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { MoreHorizontal, Pencil, Trash2 } from 'lucide-vue-next'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Button } from '@/components/ui/button'
import type { SessionSummary } from '@/lib/types'
import { useRelativeTime } from '@/composables/useRelativeTime'
import { truncate } from '@/lib/format'

const props = defineProps<{
  session: SessionSummary
  active: boolean
}>()

const emit = defineEmits<{
  (e: 'select'): void
  (e: 'rename', title: string): void
  (e: 'delete'): void
}>()

const editing = ref(false)
const draft = ref('')
const inputRef = ref<HTMLInputElement | null>(null)

const { text: relative } = useRelativeTime(() => props.session.updated_at)

const preview = computed(() => {
  const p =
    props.session.last_assistant_preview ||
    props.session.last_user_message ||
    ''
  return truncate(p, 80)
})

async function startEdit() {
  draft.value = props.session.title
  editing.value = true
  await nextTick()
  inputRef.value?.focus()
  inputRef.value?.select()
}

function commit() {
  const next = draft.value.trim()
  editing.value = false
  if (!next || next === props.session.title) return
  emit('rename', next)
}

function cancel() {
  editing.value = false
}

function onClick(e: MouseEvent) {
  if (editing.value) return
  const t = e.target as HTMLElement
  if (t.closest('[data-no-select]')) return
  emit('select')
}
</script>

<template>
  <div
    role="option"
    :aria-selected="active"
    class="group relative flex w-full items-start gap-2 rounded-md px-2 py-2 text-left transition-colors"
    :class="
      active
        ? 'bg-brand/10 text-foreground'
        : 'hover:bg-sidebar-accent/60 cursor-pointer'
    "
    @click="onClick"
  >


    <div class="min-w-0 flex-1 pl-1">
      <input
        v-if="editing"
        ref="inputRef"
        v-model="draft"
        class="w-full rounded-md border bg-background px-2 py-1 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
        data-no-select
        @blur="commit"
        @keydown.enter.prevent="commit"
        @keydown.esc.prevent="cancel"
        @click.stop
      />
      <div
        v-else
        class="truncate text-sm font-medium"
        @dblclick.stop="startEdit"
      >
        {{ session.title || 'New Chat' }}
      </div>
      <div
        v-if="!editing"
        class="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground"
      >
        <span class="truncate">{{ preview || '尚無訊息' }}</span>
      </div>
      <div
        v-if="!editing"
        class="mt-0.5 text-[10px] uppercase tracking-wide text-muted-foreground/70"
      >
        {{ relative }}
      </div>
    </div>

    <DropdownMenu>
      <DropdownMenuTrigger as-child>
        <Button
          variant="ghost"
          size="icon"
          class="size-7 shrink-0 opacity-0 transition group-hover:opacity-100 data-[state=open]:opacity-100"
          data-no-select
          aria-label="更多操作"
          @click.stop
        >
          <MoreHorizontal class="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" @click.stop>
        <DropdownMenuItem @select="startEdit">
          <Pencil class="mr-2 size-4" />
          重新命名
        </DropdownMenuItem>
        <DropdownMenuItem variant="destructive" @select="$emit('delete')">
          <Trash2 class="mr-2 size-4" />
          刪除
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  </div>
</template>

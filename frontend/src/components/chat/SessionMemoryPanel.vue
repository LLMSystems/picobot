<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  BrainCircuit,
  Clock3,
  Copy,
  Eraser,
  Layers3,
  Loader2,
  Plus,
  RefreshCw,
  StickyNote,
  Trash2,
} from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import MarkdownView from '@/components/common/MarkdownView.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useSessionMemoryStore } from '@/stores/sessionMemory'
import type { SessionMemoryNote, SessionMemoryNoteKind } from '@/lib/types'

const props = defineProps<{
  open: boolean
  sessionId: string | null
}>()

const emit = defineEmits<{ (e: 'update:open', value: boolean): void }>()

const memory = useSessionMemoryStore()
const noteDraft = ref('')
const selectedKind = ref<SessionMemoryNoteKind>('note')

const dialogOpen = computed({
  get: () => props.open,
  set: (value) => emit('update:open', value),
})

const summary = computed(() => memory.data?.summary.trim() ?? '')
const hasSummary = computed(() => memory.data?.has_summary === true && !!summary.value)
const notes = computed(() => memory.notes)
const notePlaceholder = computed(() => {
  switch (selectedKind.value) {
    case 'preference':
      return '例如：偏好使用繁體中文回答'
    case 'correction':
      return '例如：Picobot 和 Nanobot 是不同專案'
    default:
      return '補充這個對話之後值得保留的背景資訊'
  }
})

const summaryUpdatedLabel = computed(() => formatTimestamp(memory.data?.updated_at, '尚未整理'))
const canEditMemory = computed(() => memory.data?.enabled !== false && !!props.sessionId)
const canSubmitNote = computed(() =>
  canEditMemory.value && !!noteDraft.value.trim() && !memory.savingNote,
)

const kindOptions: Array<{ kind: SessionMemoryNoteKind; label: string }> = [
  { kind: 'note', label: '備註' },
  { kind: 'preference', label: '偏好' },
  { kind: 'correction', label: '修正' },
]

watch(
  () => props.sessionId,
  (id) => {
    memory.bind(id)
    noteDraft.value = ''
    selectedKind.value = 'note'
  },
  { immediate: true },
)

watch(
  () => props.open,
  (open) => {
    if (open) void memory.refresh(props.sessionId)
  },
)

function formatTimestamp(raw: string | null | undefined, fallback: string): string {
  if (!raw) return fallback
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return raw
  return new Intl.DateTimeFormat('zh-TW', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function kindLabel(kind: SessionMemoryNoteKind): string {
  switch (kind) {
    case 'preference':
      return '偏好'
    case 'correction':
      return '修正'
    default:
      return '備註'
  }
}

async function copySummary() {
  if (!summary.value) return
  try {
    await navigator.clipboard.writeText(summary.value)
    toast.success('已複製系統摘要')
  } catch {
    toast.error('複製失敗')
  }
}

async function submitNote() {
  const content = noteDraft.value.trim()
  if (!content || !props.sessionId) return
  try {
    await memory.addNote(content, selectedKind.value, props.sessionId)
    noteDraft.value = ''
    toast.success('已新增使用者記憶')
  } catch (err) {
    toast.error(err instanceof Error ? err.message : '新增記憶失敗')
  }
}

async function removeNote(note: SessionMemoryNote) {
  if (!props.sessionId) return
  if (!confirm('確定停用這條使用者記憶嗎？')) return
  try {
    await memory.deleteNote(note.id, props.sessionId)
    toast.success('已停用使用者記憶')
  } catch (err) {
    toast.error(err instanceof Error ? err.message : '停用記憶失敗')
  }
}

async function clearSummary() {
  if (!props.sessionId || !hasSummary.value) return
  if (!confirm('確定清除目前的系統摘要嗎？原始對話仍會保留。')) return
  try {
    await memory.clearSummary(props.sessionId)
    toast.success('已清除系統摘要')
  } catch (err) {
    toast.error(err instanceof Error ? err.message : '清除摘要失敗')
  }
}
</script>

<template>
  <Dialog v-model:open="dialogOpen">
    <DialogContent class="max-h-[88vh] overflow-hidden p-0 sm:max-w-3xl">
      <DialogHeader class="border-b px-5 py-4">
        <div class="flex items-start gap-3 pr-8">
          <div class="mt-0.5 grid size-8 shrink-0 place-items-center rounded-md border bg-muted">
            <BrainCircuit class="size-4 text-muted-foreground" />
          </div>
          <div class="min-w-0 flex-1">
            <DialogTitle class="text-base">會話記憶</DialogTitle>
            <DialogDescription>
              上半部是系統整理的舊對話摘要，下半部是你手動補充給 Picobot 的記憶。
            </DialogDescription>
          </div>
        </div>
      </DialogHeader>

      <div class="max-h-[72vh] overflow-y-auto px-5 py-4">
        <div
          v-if="memory.loading && !memory.data"
          class="flex items-center gap-2 rounded-xl border bg-muted/30 px-4 py-10 text-sm text-muted-foreground"
        >
          <Loader2 class="size-4 animate-spin" />
          正在載入會話記憶…
        </div>

        <div v-else class="space-y-4">
          <div
            v-if="memory.lastError"
            class="rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive"
          >
            {{ memory.lastError.message }}
          </div>

          <section class="rounded-xl border bg-background/80 p-4 shadow-sm">
            <div class="flex flex-wrap items-start gap-3">
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <h3 class="text-sm font-medium">系統摘要</h3>
                  <Badge variant="outline" class="gap-1 rounded-md px-2 py-0.5">
                    <Layers3 class="size-3" />
                    {{ memory.compactedCount }} 則
                  </Badge>
                  <Badge variant="outline" class="gap-1 rounded-md px-2 py-0.5">
                    <Clock3 class="size-3" />
                    {{ summaryUpdatedLabel }}
                  </Badge>
                </div>
                <p class="mt-1 text-xs text-muted-foreground">
                  這份摘要由系統自動整理，用來延續較早的對話上下文。
                </p>
              </div>
              <div class="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  class="size-8"
                  aria-label="重新整理會話記憶"
                  title="重新整理"
                  :disabled="memory.loading"
                  @click="memory.refresh(sessionId)"
                >
                  <Loader2 v-if="memory.loading" class="size-4 animate-spin" />
                  <RefreshCw v-else class="size-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  class="size-8"
                  aria-label="複製系統摘要"
                  title="複製摘要"
                  :disabled="!hasSummary"
                  @click="copySummary"
                >
                  <Copy class="size-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  class="size-8"
                  aria-label="清除系統摘要"
                  title="清除摘要"
                  :disabled="!hasSummary || memory.clearingSummary"
                  @click="clearSummary"
                >
                  <Loader2 v-if="memory.clearingSummary" class="size-4 animate-spin" />
                  <Eraser v-else class="size-4" />
                </Button>
              </div>
            </div>

            <div class="mt-4">
              <div
                v-if="memory.data && !memory.data.enabled"
                class="rounded-lg border bg-muted/40 px-3 py-3 text-sm text-muted-foreground"
              >
                這個對話沒有啟用記憶功能。
              </div>
              <div
                v-else-if="!hasSummary"
                class="rounded-lg border bg-muted/40 px-3 py-3 text-sm text-muted-foreground"
              >
                目前尚未產生系統摘要。
              </div>
              <MarkdownView
                v-else
                :content="summary"
                class="rounded-lg border bg-muted/10 px-4 py-3 text-sm"
              />
            </div>
          </section>

          <section class="rounded-xl border bg-background/80 p-4 shadow-sm">
            <div class="flex items-start gap-3">
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <StickyNote class="size-4 text-muted-foreground" />
                  <h3 class="text-sm font-medium">使用者記憶</h3>
                  <Badge variant="outline" class="rounded-md px-2 py-0.5">
                    {{ notes.length }} 條
                  </Badge>
                </div>
                <p class="mt-1 text-xs text-muted-foreground">
                  你可以補充偏好、修正或背景資訊。這些內容會和系統摘要分開保存，並一起進入後續上下文。
                </p>
              </div>
            </div>

            <div class="mt-4 rounded-lg border bg-muted/10 p-3">
              <Label class="text-xs text-muted-foreground">新增記憶</Label>
              <div class="mt-2 flex flex-wrap gap-2">
                <Button
                  v-for="item in kindOptions"
                  :key="item.kind"
                  variant="outline"
                  size="sm"
                  class="h-7 px-2 text-xs"
                  :class="selectedKind === item.kind ? 'border-sky-500 bg-sky-50 text-sky-700' : ''"
                  :disabled="!canEditMemory"
                  @click="selectedKind = item.kind"
                >
                  {{ item.label }}
                </Button>
              </div>
              <Textarea
                v-model="noteDraft"
                :disabled="!canEditMemory || memory.savingNote"
                :placeholder="notePlaceholder"
                class="mt-3 min-h-24 resize-y bg-background text-sm"
              />
              <div class="mt-3 flex items-center justify-between gap-3">
                <p class="text-[11px] text-muted-foreground">
                  這些記憶會優先被當成使用者明示的偏好或修正。
                </p>
                <Button
                  size="sm"
                  class="h-8 px-3 text-xs"
                  :disabled="!canSubmitNote"
                  @click="submitNote"
                >
                  <Loader2 v-if="memory.savingNote" class="mr-1 size-3.5 animate-spin" />
                  <Plus v-else class="mr-1 size-3.5" />
                  新增記憶
                </Button>
              </div>
            </div>

            <div class="mt-4 space-y-3">
              <div
                v-if="!notes.length"
                class="rounded-lg border bg-muted/40 px-3 py-3 text-sm text-muted-foreground"
              >
                目前沒有使用者記憶。
              </div>

              <div
                v-for="note in notes"
                :key="note.id"
                class="rounded-lg border bg-background px-4 py-3"
              >
                <div class="flex items-start gap-3">
                  <div class="min-w-0 flex-1">
                    <div class="flex flex-wrap items-center gap-2">
                      <Badge variant="secondary" class="rounded-md px-2 py-0.5">
                        {{ kindLabel(note.kind) }}
                      </Badge>
                      <span class="text-xs text-muted-foreground">
                        {{ formatTimestamp(note.updated_at, note.updated_at) }}
                      </span>
                    </div>
                    <p class="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-foreground">
                      {{ note.content }}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    class="size-8 shrink-0"
                    aria-label="停用使用者記憶"
                    title="停用記憶"
                    :disabled="memory.deletingNoteId === note.id"
                    @click="removeNote(note)"
                  >
                    <Loader2
                      v-if="memory.deletingNoteId === note.id"
                      class="size-4 animate-spin"
                    />
                    <Trash2 v-else class="size-4" />
                  </Button>
                </div>
              </div>
            </div>
          </section>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Check, X, CircleSlash, Wrench, Hash, Cpu } from 'lucide-vue-next'
import SubagentAvatar from './SubagentAvatar.vue'
import { truncate } from '@/lib/format'
import { toolDisplayName } from '@/lib/toolDisplay'
import { useElapsed } from '@/composables/useElapsed'
import { useCapabilitiesStore } from '@/stores/capabilities'
import { useSubagentStore } from '@/stores/subagents'
import type { SubagentSummary } from '@/lib/types'

const props = defineProps<{
  summary: SubagentSummary
  selected: boolean
}>()

defineEmits<{ (e: 'select', taskId: string): void }>()

const subagents = useSubagentStore()
const caps = useCapabilitiesStore()

const isRunning = computed(
  () =>
    props.summary.phase === 'running' || props.summary.phase === 'spawned',
)

const phaseColor = computed(() => {
  switch (props.summary.phase) {
    case 'running':
    case 'spawned':
      return 'bg-amber-400'
    case 'done':
      return 'bg-emerald-500'
    case 'failed':
      return 'bg-red-500'
    case 'cancelled':
      return 'bg-muted-foreground/60'
    default:
      return 'bg-muted-foreground/60'
  }
})

// Always read the in-memory streaming snapshot if present — it survives the
// running → done transition until a page reload, and is more accurate than
// the persisted summary's `tool_events` (which may not be backfilled).
const liveStreaming = computed(() =>
  subagents.getStreaming(props.summary.task_id),
)

// "Currently using <tool>" subtitle for running subagents only.
const currentTool = computed(() => {
  if (!isRunning.value) return null
  const calls = liveStreaming.value?.toolCalls ?? []
  for (let i = calls.length - 1; i >= 0; i--) {
    const tc = calls[i]
    if (tc && tc.status === 'running') {
      return toolDisplayName(tc.name, caps.toolMap.get(tc.name))
    }
  }
  return null
})

const toolsCount = computed(() => {
  const live = liveStreaming.value
  if (live && live.toolCalls.length > 0) return live.toolCalls.length
  return props.summary.tool_events?.length ?? 0
})

const stepsCount = computed(() => {
  const live = liveStreaming.value
  if (live && live.segments.length > 0) return live.segments.length
  return props.summary.tool_events?.length ?? 0
})

const { text: elapsedText } = useElapsed(
  () => props.summary.started_at,
  () => props.summary.finished_at,
)
</script>

<template>
  <button
    type="button"
    class="group relative flex w-full items-center gap-2.5 overflow-hidden rounded-lg border bg-card p-2.5 text-left text-sm transition-all"
    :class="
      selected
        ? 'border-brand/50 bg-brand/5 shadow-sm'
        : 'border-border hover:border-foreground/20 hover:bg-muted/40'
    "
    @click="$emit('select', summary.task_id)"
  >
    <span
      class="absolute inset-y-0 left-0 w-1"
      :class="phaseColor"
      aria-hidden="true"
    />

    <SubagentAvatar
      :task-id="summary.task_id"
      :running="isRunning"
      class="ml-1"
    />

    <div class="min-w-0 flex-1 space-y-0.5">
      <div class="flex items-start gap-1.5">
        <div class="min-w-0 flex-1 truncate font-medium leading-tight">
          {{ summary.label || summary.task_id }}
        </div>
        <span class="ml-auto shrink-0 text-[10px] text-muted-foreground">
          {{ elapsedText }}
        </span>
      </div>

      <div
        v-if="currentTool"
        class="flex items-center gap-1 truncate text-[11px] text-amber-600 dark:text-amber-400"
      >
        <Wrench class="size-3 shrink-0 animate-pulse" />
        <span class="truncate">正在使用 {{ currentTool }}…</span>
      </div>
      <div
        v-else-if="isRunning"
        class="flex items-center gap-1 truncate text-[11px] text-muted-foreground"
      >
        <span class="flex gap-0.5">
          <span class="size-1 animate-bounce rounded-full bg-amber-500 [animation-delay:-0.3s]" />
          <span class="size-1 animate-bounce rounded-full bg-amber-500 [animation-delay:-0.15s]" />
          <span class="size-1 animate-bounce rounded-full bg-amber-500" />
        </span>
        <span class="truncate">思考中…</span>
      </div>
      <div
        v-else-if="summary.task"
        class="truncate text-[11px] text-muted-foreground"
      >
        {{ truncate(summary.task, 60) }}
      </div>

      <div class="flex flex-wrap items-center gap-x-2 gap-y-0.5 pt-0.5 text-[10px] text-muted-foreground">
        <span class="flex items-center gap-0.5">
          <Hash class="size-2.5" />{{ stepsCount }} 步
        </span>
        <span aria-hidden="true">·</span>
        <span class="flex items-center gap-0.5">
          <Wrench class="size-2.5" />{{ toolsCount }} 工具
        </span>
        <span
          v-if="summary.model"
          aria-hidden="true"
        >·</span>
        <span
          v-if="summary.model"
          class="flex items-center gap-0.5 truncate font-mono"
          :title="`Model: ${summary.model}`"
        >
          <Cpu class="size-2.5" />{{ summary.model }}
        </span>
        <span aria-hidden="true">·</span>
        <span class="flex items-center gap-0.5">
          <Check
            v-if="summary.phase === 'done'"
            class="size-2.5 text-emerald-500"
          />
          <X
            v-else-if="summary.phase === 'failed'"
            class="size-2.5 text-red-500"
          />
          <CircleSlash
            v-else-if="summary.phase === 'cancelled'"
            class="size-2.5"
          />
          <span
            v-else
            class="inline-block size-1.5 animate-pulse rounded-full bg-amber-500"
          />
          {{
            summary.phase === 'done'
              ? '完成'
              : summary.phase === 'failed'
                ? '失敗'
                : summary.phase === 'cancelled'
                  ? '已取消'
                  : '進行中'
          }}
        </span>
      </div>
    </div>
  </button>
</template>

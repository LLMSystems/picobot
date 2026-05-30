<script setup lang="ts">
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useElapsed } from '@/composables/useElapsed'
import type {
    DisplayMessageSegment,
    DisplayToolCall,
    SubagentSummary,
    SubagentTimelineEvent,
} from '@/lib/types'
import { useSubagentStore } from '@/stores/subagents'
import { Coins, Cpu, Hash, Loader2, Timer, Wrench, X } from 'lucide-vue-next'
import { computed } from 'vue'
import SubagentAvatar from './SubagentAvatar.vue'
import SubagentTimeline from './SubagentTimeline.vue'

const props = defineProps<{
  summary: SubagentSummary
  closable?: boolean
}>()

defineEmits<{ (e: 'close'): void }>()

const subagents = useSubagentStore()

const isLive = computed(
  () => props.summary.phase === 'running' || props.summary.phase === 'spawned',
)

// Keep reading streaming cache even after phase transitions to terminal —
// the in-memory snapshot is the most accurate source until the page reloads.
const liveStreaming = computed(() =>
  subagents.getStreaming(props.summary.task_id),
)

const hasLiveSnapshot = computed(() => {
  const s = liveStreaming.value
  if (!s) return false
  return s.segments.length > 0 || s.content.length > 0 || isLive.value
})

const historyTimeline = computed<SubagentTimelineEvent[]>(() => {
  if (hasLiveSnapshot.value) return []
  return subagents.getTimeline(props.summary.task_id)
})

const historyLoading = computed(
  () =>
    !hasLiveSnapshot.value &&
    subagents.loadingTimeline === props.summary.task_id &&
    historyTimeline.value.length === 0,
)

function reconstructFromTimeline(events: SubagentTimelineEvent[]): {
  segments: DisplayMessageSegment[]
} {
  const segments: DisplayMessageSegment[] = []
  const calls = new Map<string, DisplayToolCall>()
  const sorted = [...events].sort((a, b) => a.seq - b.seq)
  for (const ev of sorted) {
    const payload = (ev.payload?.data ?? ev.payload) as Record<string, unknown>
    switch (ev.event_type) {
      case 'subagent_delta': {
        const d = payload?.delta
        if (typeof d !== 'string' || !d) break
        const last = segments[segments.length - 1]
        if (last && last.type === 'text') {
          last.content += d
        } else {
          segments.push({ type: 'text', content: d })
        }
        break
      }
      case 'subagent_tool_call_started': {
        const id = String(payload?.id ?? '')
        const name = String(payload?.name ?? '')
        if (!id || !name) break
        const args =
          (payload?.arguments as Record<string, unknown> | undefined) ?? {}
        const tc: DisplayToolCall = {
          id,
          name,
          arguments: args,
          status: 'running',
        }
        calls.set(id, tc)
        segments.push({ type: 'tool', toolCall: tc })
        break
      }
      case 'subagent_tool_call_finished': {
        const id = String(payload?.id ?? '')
        const tc = calls.get(id)
        if (!tc) break
        const ok = payload?.ok !== false
        tc.ok = ok
        tc.result = payload?.result
        tc.status = ok ? 'ok' : 'failed'
        break
      }
      default:
        break
    }
  }
  return { segments }
}

const reconstructed = computed(() =>
  hasLiveSnapshot.value
    ? { segments: [] as DisplayMessageSegment[] }
    : reconstructFromTimeline(historyTimeline.value),
)

const segments = computed<DisplayMessageSegment[]>(() => {
  if (hasLiveSnapshot.value) return liveStreaming.value?.segments ?? []
  if (reconstructed.value.segments.length > 0) {
    return reconstructed.value.segments
  }
  const final = props.summary.final_content
  if (final) return [{ type: 'text', content: final }]
  return []
})

const phaseBadgeVariant = computed<
  'default' | 'secondary' | 'destructive' | 'outline'
>(() => {
  switch (props.summary.phase) {
    case 'done':
      return 'secondary'
    case 'failed':
      return 'destructive'
    case 'cancelled':
      return 'outline'
    default:
      return 'default'
  }
})

const phaseLabel = computed(() => {
  switch (props.summary.phase) {
    case 'spawned':
      return '準備中'
    case 'running':
      return '執行中'
    case 'done':
      return '完成'
    case 'failed':
      return '失敗'
    case 'cancelled':
      return '已取消'
    default:
      return props.summary.phase
  }
})

const { text: elapsedText } = useElapsed(
  () => props.summary.started_at,
  () => props.summary.finished_at,
)

const tokensText = computed(() => {
  const usage = props.summary.usage ?? {}
  const candidates: number[] = []
  for (const v of Object.values(usage)) {
    if (typeof v === 'number' && Number.isFinite(v)) candidates.push(v)
  }
  const totalKey = (usage as Record<string, unknown>).total_tokens
  if (typeof totalKey === 'number') return totalKey.toLocaleString()
  const sum = candidates.reduce((a, b) => a + b, 0)
  return sum > 0 ? sum.toLocaleString() : '—'
})

const stepsCount = computed(() => segments.value.length)
const toolsCount = computed(
  () =>
    segments.value.filter((s): s is Extract<DisplayMessageSegment, { type: 'tool' }> => s.type === 'tool').length,
)
</script>

<template>
  <div class="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
    <div class="shrink-0 border-b bg-background/80 px-3 py-2 backdrop-blur">
      <div class="flex items-start gap-2">
        <SubagentAvatar
          :task-id="summary.task_id"
          :running="isLive"
          size="md"
        />
        <div class="min-w-0 flex-1">
          <div class="truncate text-sm font-medium">
            {{ summary.label || summary.task_id }}
          </div>
          <div class="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
            <Badge
              :variant="phaseBadgeVariant"
              class="h-4 px-1.5 text-[10px]"
            >
              <span
                v-if="isLive"
                class="mr-1 inline-block size-1.5 animate-pulse rounded-full bg-amber-400"
              />
              {{ phaseLabel }}
            </Badge>
            <Badge
              v-if="summary.model"
              variant="outline"
              class="h-4 gap-1 px-1.5 font-mono text-[10px]"
              :title="`Model: ${summary.model}`"
            >
              <Cpu class="size-2.5" />
              {{ summary.model }}
            </Badge>
            <span class="font-mono text-[10px] opacity-70">
              {{ summary.task_id }}
            </span>
          </div>
        </div>
        <Button
          v-if="closable"
          variant="ghost"
          size="icon"
          class="size-7 shrink-0"
          aria-label="關閉此任務"
          @click="$emit('close')"
        >
          <X class="size-4" />
        </Button>
      </div>

      <!-- Stats strip -->
      <div
        class="mt-2 grid grid-cols-4 gap-2 rounded-md border bg-muted/30 p-2 text-[11px]"
      >
        <div class="flex flex-col items-center gap-0.5">
          <span class="flex items-center gap-1 text-muted-foreground">
            <Timer class="size-3" />經過
          </span>
          <span class="font-mono text-foreground">{{ elapsedText }}</span>
        </div>
        <div class="flex flex-col items-center gap-0.5">
          <span class="flex items-center gap-1 text-muted-foreground">
            <Hash class="size-3" />步數
          </span>
          <span class="font-mono text-foreground">{{ stepsCount }}</span>
        </div>
        <div class="flex flex-col items-center gap-0.5">
          <span class="flex items-center gap-1 text-muted-foreground">
            <Wrench class="size-3" />工具
          </span>
          <span class="font-mono text-foreground">{{ toolsCount }}</span>
        </div>
        <div class="flex flex-col items-center gap-0.5">
          <span class="flex items-center gap-1 text-muted-foreground">
            <Coins class="size-3" />tokens
          </span>
          <span class="font-mono text-foreground">{{ tokensText }}</span>
        </div>
      </div>
    </div>

    <div class="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden px-3 py-3">
      <div
        v-if="historyLoading"
        class="flex items-center justify-center gap-2 py-6 text-xs text-muted-foreground"
      >
        <Loader2 class="size-3.5 animate-spin" />
        載入歷史紀錄…
      </div>
      <SubagentTimeline
        v-else
        :summary="summary"
        :segments="segments"
        :live="isLive"
      />
    </div>
  </div>
</template>

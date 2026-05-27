<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Bot, Loader2 } from 'lucide-vue-next'
import SubagentListItem from './SubagentListItem.vue'
import SubagentDetail from './SubagentDetail.vue'
import { useSubagentStore } from '@/stores/subagents'
import type { SubagentSummary } from '@/lib/types'

const subagents = useSubagentStore()

const NARROW_BREAKPOINT = 520
const panelRef = ref<HTMLElement | null>(null)
const containerWidth = ref<number>(Number.POSITIVE_INFINITY)

let observer: ResizeObserver | null = null

onMounted(() => {
  const el = panelRef.value
  if (!el) return
  if (typeof ResizeObserver === 'undefined') return
  observer = new ResizeObserver((entries) => {
    for (const entry of entries) {
      containerWidth.value = entry.contentRect.width
    }
  })
  observer.observe(el)
})

const isNarrow = computed(() => containerWidth.value < NARROW_BREAKPOINT)

type Filter = 'all' | 'running' | 'done' | 'failed'

const activeFilter = ref<Filter>('all')

function isRunning(s: SubagentSummary): boolean {
  return s.phase === 'running' || s.phase === 'spawned'
}

const counts = computed(() => {
  let running = 0
  let done = 0
  let failed = 0
  for (const s of subagents.sortedSummaries) {
    if (isRunning(s)) running += 1
    else if (s.phase === 'done') done += 1
    else if (s.phase === 'failed' || s.phase === 'cancelled') failed += 1
  }
  return { all: subagents.sortedSummaries.length, running, done, failed }
})

const filtered = computed<SubagentSummary[]>(() => {
  const list = subagents.sortedSummaries
  switch (activeFilter.value) {
    case 'running':
      return list.filter(isRunning)
    case 'done':
      return list.filter((s) => s.phase === 'done')
    case 'failed':
      return list.filter(
        (s) => s.phase === 'failed' || s.phase === 'cancelled',
      )
    default:
      return list
  }
})

// Group "all" view: running first, then everything else, ordered by started_at desc.
const groupedAll = computed(() => {
  if (activeFilter.value !== 'all') {
    return [{ key: 'all', label: '', items: filtered.value }]
  }
  const running: SubagentSummary[] = []
  const finished: SubagentSummary[] = []
  for (const s of filtered.value) {
    if (isRunning(s)) running.push(s)
    else finished.push(s)
  }
  const groups: Array<{ key: string; label: string; items: SubagentSummary[] }> = []
  if (running.length > 0) {
    groups.push({ key: 'running', label: '進行中', items: running })
  }
  if (finished.length > 0) {
    groups.push({ key: 'finished', label: '已完成', items: finished })
  }
  return groups
})

const selectedSummary = computed(() => subagents.selectedSummary)
const showDetail = computed(() => selectedSummary.value !== null)
const showList = computed(() => !isNarrow.value || !showDetail.value)

function onSelect(taskId: string) {
  subagents.selectTask(taskId)
}

function onBack() {
  subagents.selectTask(null)
}

function chipClass(f: Filter): string {
  const base =
    'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] transition-colors'
  return activeFilter.value === f
    ? `${base} bg-brand/15 text-brand border border-brand/30`
    : `${base} border border-transparent text-muted-foreground hover:bg-muted/60`
}
</script>

<template>
  <section
    ref="panelRef"
    class="flex min-h-0 w-full overflow-hidden"
  >
    <!-- List column -->
    <div
      v-if="showList"
      class="flex min-h-0 flex-col border-r bg-background"
      :class="
        isNarrow ? 'w-full' : 'w-[42%] max-w-[320px] min-w-[200px]'
      "
    >
      <!-- Filter chips -->
      <div
        v-if="subagents.sortedSummaries.length > 0"
        class="flex shrink-0 items-center gap-1 overflow-x-auto border-b px-2 py-1.5"
      >
        <button
          type="button"
          :class="chipClass('all')"
          @click="activeFilter = 'all'"
        >
          全部
          <span class="text-[10px] opacity-70">{{ counts.all }}</span>
        </button>
        <button
          type="button"
          :class="chipClass('running')"
          @click="activeFilter = 'running'"
        >
          <span
            v-if="counts.running > 0"
            class="size-1.5 animate-pulse rounded-full bg-amber-500"
          />
          進行中
          <span class="text-[10px] opacity-70">{{ counts.running }}</span>
        </button>
        <button
          type="button"
          :class="chipClass('done')"
          @click="activeFilter = 'done'"
        >
          已完成
          <span class="text-[10px] opacity-70">{{ counts.done }}</span>
        </button>
        <button
          type="button"
          :class="chipClass('failed')"
          @click="activeFilter = 'failed'"
        >
          失敗
          <span class="text-[10px] opacity-70">{{ counts.failed }}</span>
        </button>
      </div>

      <!-- Body -->
      <div
        v-if="subagents.loadingSummaries"
        class="flex items-center justify-center gap-2 py-6 text-xs text-muted-foreground"
      >
        <Loader2 class="size-3.5 animate-spin" />
        載入中…
      </div>
      <div
        v-else-if="subagents.sortedSummaries.length === 0"
        class="flex h-full flex-col items-center justify-center gap-3 px-6 text-center"
      >
        <span
          class="inline-flex size-12 items-center justify-center rounded-full bg-brand/10"
        >
          <Bot class="size-6 text-brand" />
        </span>
        <div class="space-y-1">
          <div class="text-sm font-medium">尚未產生子任務</div>
          <div class="text-[11px] text-muted-foreground">
            主代理可以分派子任務，<br />進度會即時顯示在這裡。
          </div>
        </div>
      </div>
      <div
        v-else
        class="min-h-0 flex-1 space-y-3 overflow-y-auto p-2"
      >
        <template v-for="group in groupedAll" :key="group.key">
          <div v-if="group.items.length > 0" class="space-y-1.5">
            <div
              v-if="group.label"
              class="flex items-center gap-1.5 px-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground"
            >
              {{ group.label }}
              <span class="opacity-60">·</span>
              <span class="opacity-60">{{ group.items.length }}</span>
            </div>
            <SubagentListItem
              v-for="s in group.items"
              :key="s.task_id"
              :summary="s"
              :selected="subagents.selectedTaskId === s.task_id"
              @select="onSelect"
            />
          </div>
        </template>
        <div
          v-if="filtered.length === 0"
          class="px-2 py-6 text-center text-[11px] text-muted-foreground"
        >
          沒有符合的任務
        </div>
      </div>
    </div>

    <!-- Detail column -->
    <div
      v-if="showDetail || !isNarrow"
      class="min-h-0 flex-1 bg-background"
    >
      <SubagentDetail
        v-if="selectedSummary"
        :summary="selectedSummary"
        :show-back="isNarrow"
        @back="onBack"
      />
      <div
        v-else
        class="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-xs text-muted-foreground"
      >
        <Bot class="size-8 opacity-40" />
        <div>從左側選擇一個任務以查看詳情</div>
      </div>
    </div>
  </section>
</template>

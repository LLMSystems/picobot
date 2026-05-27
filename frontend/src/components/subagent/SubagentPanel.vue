<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
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

// Wide layout renders every pinned subagent side-by-side.
// Narrow layout shows just the most-recently-opened one.
const openSet = computed(() => new Set(subagents.openTaskIds))
const wideOpenSummaries = computed(() => subagents.openSummaries)
const narrowOpenSummary = computed(() =>
  wideOpenSummaries.value.length > 0
    ? wideOpenSummaries.value[wideOpenSummaries.value.length - 1]
    : null,
)

const showDetail = computed(() =>
  isNarrow.value
    ? narrowOpenSummary.value !== null
    : wideOpenSummaries.value.length > 0,
)
const showList = computed(() => !isNarrow.value || !showDetail.value)

function onSelect(taskId: string) {
  subagents.openTask(taskId)
}

function onClose(taskId: string) {
  subagents.closeTask(taskId)
}

// Column width overrides (px) keyed by task_id.
// Empty → all columns share equally via flex-1.
// Whenever the set of open tasks changes, reset to equal share.
const COLUMN_MIN_WIDTH = 240
const columnWidths = ref<Map<string, number>>(new Map())

watch(
  () => subagents.openTaskIds.slice().join('|'),
  () => {
    columnWidths.value = new Map()
  },
)

function columnStyle(taskId: string): Record<string, string> {
  const w = columnWidths.value.get(taskId)
  if (w !== undefined) {
    return { width: `${w}px`, flex: '0 0 auto' }
  }
  return { flex: '1 1 0%' }
}

function startColumnResize(e: PointerEvent, leftId: string, rightId: string) {
  const handle = e.currentTarget
  if (!(handle instanceof HTMLElement)) return
  const leftEl = handle.previousElementSibling
  const rightEl = handle.nextElementSibling
  if (!(leftEl instanceof HTMLElement) || !(rightEl instanceof HTMLElement)) return
  e.preventDefault()

  const startX = e.clientX
  const startLeftW = leftEl.offsetWidth
  const startRightW = rightEl.offsetWidth

  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'

  function onMove(ev: PointerEvent) {
    const delta = ev.clientX - startX
    let newLeft = startLeftW + delta
    let newRight = startRightW - delta
    if (newLeft < COLUMN_MIN_WIDTH) {
      newRight -= COLUMN_MIN_WIDTH - newLeft
      newLeft = COLUMN_MIN_WIDTH
    }
    if (newRight < COLUMN_MIN_WIDTH) {
      newLeft -= COLUMN_MIN_WIDTH - newRight
      newRight = COLUMN_MIN_WIDTH
    }
    const next = new Map(columnWidths.value)
    next.set(leftId, newLeft)
    next.set(rightId, newRight)
    columnWidths.value = next
  }

  function onUp() {
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
    window.removeEventListener('pointercancel', onUp)
  }

  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
  window.addEventListener('pointercancel', onUp)
}

function chipClass(f: Filter): string {
  const base =
    'inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] transition-colors'
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
      class="flex min-h-0 shrink-0 flex-col border-r bg-background"
      :class="
        isNarrow ? 'w-full' : 'w-[42%] max-w-[320px] min-w-[200px]'
      "
    >
      <div
        v-if="subagents.sortedSummaries.length > 0"
        class="flex shrink-0 items-center gap-1 overflow-x-auto border-b px-2 py-1.5"
      >
        <button type="button" :class="chipClass('all')" @click="activeFilter = 'all'">
          全部 <span class="text-[10px] opacity-70">{{ counts.all }}</span>
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
        <button type="button" :class="chipClass('done')" @click="activeFilter = 'done'">
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
        <span class="inline-flex size-12 items-center justify-center rounded-full bg-brand/10">
          <Bot class="size-6 text-brand" />
        </span>
        <div class="space-y-1">
          <div class="text-sm font-medium">尚未產生子任務</div>
          <div class="text-[11px] text-muted-foreground">
            主代理可以分派子任務，<br />進度會即時顯示在這裡。
          </div>
        </div>
      </div>
      <div v-else class="min-h-0 flex-1 space-y-3 overflow-y-auto p-2">
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
              :selected="openSet.has(s.task_id)"
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

    <!-- Detail area -->
    <div v-if="showDetail || !isNarrow" class="min-h-0 min-w-0 flex-1 bg-background">
      <!-- Wide: multi-column side-by-side -->
      <div
        v-if="!isNarrow"
        class="flex h-full min-h-0 w-full overflow-x-auto"
      >
        <template v-if="wideOpenSummaries.length === 0">
          <div
            class="flex h-full w-full flex-col items-center justify-center gap-2 px-6 text-center text-xs text-muted-foreground"
          >
            <Bot class="size-8 opacity-40" />
            <div>從左側選擇一個任務以查看詳情</div>
            <div class="text-[10px]">最多可同時開啟 3 個</div>
          </div>
        </template>
        <template v-else>
          <template
            v-for="(summary, i) in wideOpenSummaries"
            :key="summary.task_id"
          >
            <!-- Drag handle between columns -->
            <div
              v-if="i > 0"
              class="group relative h-full w-1.5 shrink-0 cursor-col-resize bg-border/60 transition-colors hover:bg-primary/40"
              role="separator"
              aria-orientation="vertical"
              aria-label="拖曳調整欄寬"
              @pointerdown="
                startColumnResize(
                  $event,
                  wideOpenSummaries[i - 1]!.task_id,
                  summary.task_id,
                )
              "
            >
              <span
                class="pointer-events-none absolute inset-y-0 left-1/2 -translate-x-1/2 block w-px bg-transparent group-hover:bg-primary/60"
              />
            </div>
            <div
              class="flex h-full min-w-[240px] flex-col"
              :style="columnStyle(summary.task_id)"
            >
              <SubagentDetail
                :summary="summary"
                closable
                @close="onClose(summary.task_id)"
              />
            </div>
          </template>
        </template>
      </div>

      <!-- Narrow: only the most-recently-opened -->
      <template v-else>
        <SubagentDetail
          v-if="narrowOpenSummary"
          :summary="narrowOpenSummary"
          closable
          @close="subagents.closeAllTasks()"
        />
      </template>
    </div>
  </section>
</template>

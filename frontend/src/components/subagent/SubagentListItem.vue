<script setup lang="ts">
import { computed } from 'vue'
import { Check, X, CircleSlash, Cpu, Clock } from 'lucide-vue-next'
import { useElapsed } from '@/composables/useElapsed'
import type { SubagentSummary } from '@/lib/types'
import picobotImg from '@/assets/picobot.png'

const props = defineProps<{
  summary: SubagentSummary
  selected: boolean
}>()

defineEmits<{ (e: 'select', taskId: string): void }>()

// Status pill shown top-right of the card header. `dot: true` renders a pulsing
// dot instead of an icon for the in-progress phases.
const statusConfig = computed(() => {
  switch (props.summary.phase) {
    case 'done':
      return {
        label: '完成',
        icon: Check,
        dot: false,
        pill: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
      }
    case 'failed':
      return {
        label: '失敗',
        icon: X,
        dot: false,
        pill: 'bg-red-500/10 text-red-600 dark:text-red-400',
      }
    case 'cancelled':
      return {
        label: '已取消',
        icon: CircleSlash,
        dot: false,
        pill: 'bg-muted text-muted-foreground',
      }
    default:
      return {
        label: '進行中',
        icon: null,
        dot: true,
        pill: 'bg-amber-500/10 text-amber-600 dark:text-amber-400',
      }
  }
})

const { text: elapsedText } = useElapsed(
  () => props.summary.started_at,
  () => props.summary.finished_at,
)
</script>

<template>
  <button
    type="button"
    class="group relative flex w-full items-center gap-0.5 overflow-hidden rounded-xl border bg-card py-3 pr-3 text-left text-sm transition-all hover:-translate-y-0.5"
    :class="
      selected
        ? 'border-brand/50 bg-brand/5 shadow-md'
        : 'border-border hover:border-foreground/20 hover:shadow-sm'
    "
    @click="$emit('select', summary.task_id)"
  >

    <img
      :src="picobotImg"
      alt=""
      aria-hidden="true"
      class="size-15 shrink-0 object-contain"
    />

    <!-- Content column: task (one line) + model · time -->
    <div class="flex min-w-0 flex-1 flex-col gap-1">
      <div class="flex items-center gap-2">
        <div class="min-w-0 flex-1 truncate font-medium leading-snug">
          {{ summary.label || summary.task || summary.task_id }}
        </div>
        <span
          class="inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium"
          :class="statusConfig.pill"
        >
          <span
            v-if="statusConfig.dot"
            class="inline-block size-1.5 animate-pulse rounded-full bg-current"
          />
          <component
            :is="statusConfig.icon"
            v-else-if="statusConfig.icon"
            class="size-2.5"
          />
          {{ statusConfig.label }}
        </span>
      </div>

      <div class="flex items-center gap-2 text-[10px] text-muted-foreground">
        <span
          v-if="summary.model"
          class="flex min-w-0 items-center gap-0.5 truncate font-mono"
          :title="`Model: ${summary.model}`"
        >
          <Cpu class="size-2.5 shrink-0" />{{ summary.model }}
        </span>
        <span class="ml-auto flex shrink-0 items-center gap-0.5 tabular-nums">
          <Clock class="size-2.5" />{{ elapsedText }}
        </span>
      </div>
    </div>
  </button>
</template>

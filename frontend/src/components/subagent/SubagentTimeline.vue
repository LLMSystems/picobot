<script setup lang="ts">
import { computed } from 'vue'
import {
  Play,
  Brain,
  Wrench,
  Check,
  X,
  CircleSlash,
  Loader2,
} from 'lucide-vue-next'
import MarkdownView from '@/components/common/MarkdownView.vue'
import StreamingCursor from '@/components/chat/StreamingCursor.vue'
import ToolCallCard from '@/components/chat/ToolCallCard.vue'
import type {
  DisplayMessageSegment,
  SubagentSummary,
} from '@/lib/types'

const props = defineProps<{
  summary: SubagentSummary
  segments: DisplayMessageSegment[]
  live: boolean
}>()

function formatTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

const startedLabel = computed(() => formatTime(props.summary.started_at))
const finishedLabel = computed(() => formatTime(props.summary.finished_at))

const terminalConfig = computed(() => {
  switch (props.summary.phase) {
    case 'done':
      return {
        label: '完成',
        icon: Check,
        color: 'text-emerald-500',
        ring: 'ring-emerald-500/30',
        bg: 'bg-emerald-500',
      }
    case 'failed':
      return {
        label: '失敗',
        icon: X,
        color: 'text-red-500',
        ring: 'ring-red-500/30',
        bg: 'bg-red-500',
      }
    case 'cancelled':
      return {
        label: '已取消',
        icon: CircleSlash,
        color: 'text-muted-foreground',
        ring: 'ring-muted-foreground/30',
        bg: 'bg-muted-foreground',
      }
    default:
      return null
  }
})
</script>

<template>
  <ol class="relative space-y-3 pl-7">
    <!-- Vertical guide line -->
    <span
      class="pointer-events-none absolute bottom-2 left-3 top-2 w-px bg-border"
      aria-hidden="true"
    />

    <!-- Start node -->
    <li class="relative">
      <span
        class="absolute -left-[1.625rem] top-1 inline-flex size-5 items-center justify-center rounded-full bg-background ring-2 ring-brand/30"
      >
        <Play class="size-3 text-brand" />
      </span>
      <div class="space-y-0.5">
        <div class="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          啟動
          <span v-if="startedLabel" class="ml-1 font-normal opacity-70">
            {{ startedLabel }}
          </span>
        </div>
        <div
          v-if="summary.task"
          class="break-words rounded-md bg-muted/40 px-2 py-1 text-xs text-muted-foreground"
        >
          {{ summary.task }}
        </div>
      </div>
    </li>

    <!-- Segments -->
    <li
      v-for="(seg, idx) in segments"
      :key="idx"
      class="relative"
    >
      <template v-if="seg.type === 'text'">
        <span
          class="absolute -left-[1.625rem] top-1 inline-flex size-5 items-center justify-center rounded-full bg-background ring-2 ring-sky-500/30"
        >
          <Brain class="size-3 text-sky-500" />
        </span>
        <div class="space-y-1">
          <div class="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            思考
          </div>
          <MarkdownView :content="seg.content" />
        </div>
      </template>
      <template v-else>
        <span
          class="absolute -left-[1.625rem] top-1 inline-flex size-5 items-center justify-center rounded-full bg-background"
          :class="
            seg.toolCall.status === 'failed'
              ? 'ring-2 ring-red-500/30'
              : seg.toolCall.status === 'running'
                ? 'ring-2 ring-amber-500/30'
                : 'ring-2 ring-violet-500/30'
          "
        >
          <Wrench
            class="size-3"
            :class="
              seg.toolCall.status === 'failed'
                ? 'text-red-500'
                : seg.toolCall.status === 'running'
                  ? 'animate-pulse text-amber-500'
                  : 'text-violet-500'
            "
          />
        </span>
        <div class="space-y-1">
          <div class="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            工具呼叫
          </div>
          <ToolCallCard :tool-call="seg.toolCall" />
        </div>
      </template>
    </li>

    <!-- Live "thinking" placeholder when nothing has streamed yet, or after the last node -->
    <li v-if="live" class="relative">
      <span
        class="absolute -left-[1.625rem] top-1 inline-flex size-5 items-center justify-center rounded-full bg-background ring-2 ring-amber-500/40"
      >
        <Loader2 class="size-3 animate-spin text-amber-500" />
      </span>
      <div class="flex items-center gap-1.5 text-xs text-muted-foreground">
        <span>進行中</span>
        <StreamingCursor />
      </div>
    </li>

    <!-- Terminal node -->
    <li v-else-if="terminalConfig" class="relative">
      <span
        class="absolute -left-[1.625rem] top-1 inline-flex size-5 items-center justify-center rounded-full bg-background ring-2"
        :class="terminalConfig.ring"
      >
        <component
          :is="terminalConfig.icon"
          class="size-3"
          :class="terminalConfig.color"
        />
      </span>
      <div class="space-y-0.5">
        <div class="flex items-center gap-1.5">
          <div
            class="text-[10px] font-medium uppercase tracking-wide"
            :class="terminalConfig.color"
          >
            {{ terminalConfig.label }}
          </div>
          <span
            v-if="finishedLabel"
            class="text-[10px] text-muted-foreground"
          >
            {{ finishedLabel }}
          </span>
        </div>
        <div
          v-if="summary.error"
          class="break-words rounded-md border border-destructive/30 bg-destructive/10 px-2 py-1 text-[11px] text-destructive"
        >
          {{ summary.error }}
        </div>
      </div>
    </li>
  </ol>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { Badge } from '@/components/ui/badge'
import {
  CircleCheck,
  ChevronDown,
  Loader2,
  X,
  FileText,
  Terminal,
  Search,
  Wrench,
} from 'lucide-vue-next'
import { useCapabilitiesStore } from '@/stores/capabilities'
import { formatToolResult } from '@/lib/format'
import { toolDisplayName } from '@/lib/toolDisplay'
import { toolSummary, toolErrorSummary } from '@/lib/toolSummary'
import PicobotIcon from '@/components/common/PicobotIcon.vue'
import type { DisplayToolCall } from '@/lib/types'

const SUBAGENT_TOOLS = new Set([
  'spawn',
  'list_subagents',
  'subagent_status',
  'subagent_wait',
])

const props = defineProps<{ toolCall: DisplayToolCall }>()
const caps = useCapabilitiesStore()

const meta = computed(() => caps.toolMap.get(props.toolCall.name))
const displayName = computed(() =>
  toolDisplayName(props.toolCall.name, meta.value),
)

const argsText = computed(() => {
  try {
    return JSON.stringify(props.toolCall.arguments ?? {}, null, 2)
  } catch {
    return String(props.toolCall.arguments)
  }
})

const resultText = computed(() => formatToolResult(props.toolCall.result))

const summaryLine = computed<string | null>(() => {
  if (props.toolCall.status === 'running') return null
  if (props.toolCall.status === 'failed') {
    return toolErrorSummary(props.toolCall.result)
  }
  return toolSummary(
    props.toolCall.name,
    props.toolCall.arguments,
    props.toolCall.result,
  )
})

const isLongResult = computed(() => resultText.value.split('\n').length > 50)

const isSubagentTool = computed(() => SUBAGENT_TOOLS.has(props.toolCall.name))

const categoryIcon = computed(() => {
  const c = meta.value?.category
  if (c === 'filesystem') return FileText
  if (c === 'shell') return Terminal
  if (c === 'search') return Search
  return Wrench
})

const picobotState = computed<'idle' | 'running' | 'failed'>(() => {
  if (props.toolCall.status === 'running') return 'running'
  if (props.toolCall.status === 'failed') return 'failed'
  return 'idle'
})
</script>

<template>
  <Collapsible
    class="max-w-[calc(100%-3rem)] overflow-hidden rounded-2xl rounded-bl-md border border-border/50 bg-muted/50 text-sm"
  >
    <CollapsibleTrigger
      class="flex w-full items-center gap-2 px-4 py-2 text-left"
    >
      <PicobotIcon
        v-if="isSubagentTool"
        :size="20"
        :state="picobotState"
      />
      <component
        v-else
        :is="categoryIcon"
        class="size-4 shrink-0 text-muted-foreground"
      />
      <Loader2
        v-if="toolCall.status === 'running'"
        class="size-4 shrink-0 animate-spin text-muted-foreground"
      />
      <CircleCheck
        v-else-if="toolCall.status === 'ok'"
        class="size-4 shrink-0 text-emerald-500"
      />
      <X v-else class="size-4 shrink-0 text-red-500" />
      <span class="shrink-0 text-sm">{{ displayName }}</span>
      <span
        v-if="displayName !== toolCall.name"
        class="shrink-0 font-mono text-[10px] text-muted-foreground/70"
      >
        {{ toolCall.name }}
      </span>
      <Badge
        v-if="meta?.dangerous"
        variant="outline"
        class="h-5 shrink-0 border-amber-500/40 bg-amber-500/15 px-1.5 text-[10px] text-amber-700 dark:text-amber-400"
      >
        高權限
      </Badge>
      <span
        v-if="toolCall.status === 'running'"
        class="ml-auto shrink-0 text-xs text-muted-foreground"
      >
        執行中…
      </span>
      <span
        v-else-if="summaryLine"
        class="ml-auto min-w-0 truncate text-xs"
        :class="toolCall.status === 'failed' ? 'text-red-500' : 'text-muted-foreground'"
        :title="summaryLine"
      >
        {{ summaryLine }}
      </span>
      <span
        v-else-if="toolCall.status === 'failed'"
        class="ml-auto shrink-0 text-xs text-red-500"
      >
        失敗
      </span>
      <ChevronDown
        class="ml-1 size-4 shrink-0 text-muted-foreground transition-transform [&[data-state=open]]:rotate-180"
      />
    </CollapsibleTrigger>
    <CollapsibleContent class="space-y-2 border-t border-border/50 px-4 py-2.5">
      <div>
        <div class="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
          Arguments
        </div>
        <pre
          class="whitespace-pre-wrap break-words rounded-lg border border-border/50 bg-background/80 p-3 font-mono text-xs"
          >{{ argsText }}</pre
        >
      </div>
      <div v-if="toolCall.result !== undefined">
        <div class="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
          Result
        </div>
        <pre
          class="whitespace-pre-wrap break-words rounded-lg border border-border/50 bg-background/80 p-3 font-mono text-xs"
          :class="isLongResult ? 'max-h-80 overflow-auto' : ''"
          >{{ resultText }}</pre
        >
      </div>
    </CollapsibleContent>
  </Collapsible>
</template>

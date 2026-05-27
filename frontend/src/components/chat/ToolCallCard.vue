<script setup lang="ts">
import { computed } from 'vue'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { Badge } from '@/components/ui/badge'
import {
  Check,
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
import type { DisplayToolCall } from '@/lib/types'

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

const isLongResult = computed(() => resultText.value.split('\n').length > 50)

const categoryIcon = computed(() => {
  const c = meta.value?.category
  if (c === 'filesystem') return FileText
  if (c === 'shell') return Terminal
  if (c === 'search') return Search
  return Wrench
})
</script>

<template>
  <Collapsible class="rounded-md border bg-muted/30 text-sm">
    <CollapsibleTrigger
      class="flex w-full items-center gap-2 px-3 py-2 text-left"
    >
      <component :is="categoryIcon" class="size-4 text-muted-foreground" />
      <Loader2
        v-if="toolCall.status === 'running'"
        class="size-4 animate-spin text-muted-foreground"
      />
      <Check
        v-else-if="toolCall.status === 'ok'"
        class="size-4 text-emerald-500"
      />
      <X v-else class="size-4 text-red-500" />
      <span class="text-xs">{{ displayName }}</span>
      <span
        v-if="displayName !== toolCall.name"
        class="font-mono text-[10px] text-muted-foreground/70"
      >
        {{ toolCall.name }}
      </span>
      <Badge v-if="meta?.dangerous" variant="destructive" class="h-5 px-1.5 text-[10px]">
        危險
      </Badge>
      <span class="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
        <span v-if="toolCall.status === 'running'">執行中…</span>
        <span v-else-if="toolCall.status === 'failed'">失敗</span>
        <ChevronDown
          class="size-4 transition-transform [&[data-state=open]]:rotate-180"
        />
      </span>
    </CollapsibleTrigger>
    <CollapsibleContent class="space-y-2 border-t px-3 py-2">
      <div>
        <div class="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
          Arguments
        </div>
        <pre
          class="whitespace-pre-wrap break-words rounded border bg-background/60 p-2 font-mono text-xs"
          >{{ argsText }}</pre
        >
      </div>
      <div v-if="toolCall.result !== undefined">
        <div class="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">
          Result
        </div>
        <pre
          class="whitespace-pre-wrap break-words rounded border bg-background/60 p-2 font-mono text-xs"
          :class="isLongResult ? 'max-h-80 overflow-auto' : ''"
          >{{ resultText }}</pre
        >
      </div>
    </CollapsibleContent>
  </Collapsible>
</template>

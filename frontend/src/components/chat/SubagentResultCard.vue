<script setup lang="ts">
import { computed } from 'vue'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { Button } from '@/components/ui/button'
import { CircleCheck, X, ChevronDown, ArrowRight } from 'lucide-vue-next'
import MarkdownView from '@/components/common/MarkdownView.vue'
import PicobotIcon from '@/components/common/PicobotIcon.vue'
import { useSubagentStore } from '@/stores/subagents'
import { useWorkspaceStore } from '@/stores/workspace'
import type { DisplayMessage } from '@/lib/types'

const props = defineProps<{ message: DisplayMessage }>()

const subagents = useSubagentStore()
const ws = useWorkspaceStore()

const payload = computed(() => props.message.subagent)

function openInPanel() {
  const p = payload.value
  if (!p) return
  subagents.selectTask(p.taskId)
  ws.focusAgents()
}
</script>

<template>
  <Collapsible
    v-if="payload"
    class="w-full max-w-[calc(100%-3rem)] overflow-hidden rounded-2xl rounded-bl-md border border-border/50 bg-muted/50 text-sm"
  >
    <div class="flex items-center gap-2 px-4 py-2">
      <PicobotIcon :size="20" :state="payload.ok ? 'done' : 'failed'" />
      <CircleCheck v-if="payload.ok" class="size-4 text-emerald-500" />
      <X v-else class="size-4 text-red-500" />
      <span class="min-w-0 flex-1 truncate text-sm">
        子任務完成：<span class="font-medium">{{ payload.label }}</span>
      </span>
      <Button
        variant="ghost"
        size="sm"
        class="h-6 gap-1 px-2 text-[11px]"
        @click="openInPanel"
      >
        查看
        <ArrowRight class="size-3" />
      </Button>
      <CollapsibleTrigger
        class="inline-flex size-6 items-center justify-center rounded text-muted-foreground hover:bg-muted"
        aria-label="展開／收合"
      >
        <ChevronDown
          class="size-4 transition-transform [&[data-state=open]]:rotate-180"
        />
      </CollapsibleTrigger>
    </div>
    <CollapsibleContent class="space-y-2 border-t border-border/50 px-4 py-2.5">
        <div v-if="payload.task">
          <div
            class="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground"
          >
            Task
          </div>
          <div class="whitespace-pre-wrap break-words text-xs">
            {{ payload.task }}
          </div>
        </div>
        <div>
          <div
            class="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground"
          >
            Result
          </div>
          <MarkdownView :content="payload.result" />
        </div>
        <div
          v-if="payload.stopReason && payload.stopReason !== 'stop'"
          class="text-[11px] text-muted-foreground"
        >
          stop_reason: <span class="font-mono">{{ payload.stopReason }}</span>
        </div>
    </CollapsibleContent>
  </Collapsible>
</template>

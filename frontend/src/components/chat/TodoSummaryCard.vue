<script setup lang="ts">
import { computed } from 'vue'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import type { DisplayMessage, TodoItem } from '@/lib/types'
import { CheckCircle2, ChevronDown, Circle, CircleDot, ListChecks } from 'lucide-vue-next'

const props = defineProps<{ message: DisplayMessage }>()

const snapshot = computed(() => props.message.todoSnapshot ?? null)

const allDone = computed(
  () =>
    !!snapshot.value &&
    snapshot.value.total > 0 &&
    snapshot.value.completed === snapshot.value.total,
)

function iconFor(t: TodoItem) {
  if (t.status === 'completed') return CheckCircle2
  if (t.status === 'in_progress') return CircleDot
  return Circle
}

function iconClass(t: TodoItem) {
  if (t.status === 'completed') return 'text-emerald-500'
  if (t.status === 'in_progress') return 'text-primary'
  return 'text-muted-foreground/40'
}

function labelClass(t: TodoItem) {
  if (t.status === 'completed')
    return 'text-muted-foreground line-through decoration-muted-foreground/30'
  if (t.status === 'in_progress') return 'text-foreground font-medium'
  return 'text-muted-foreground'
}
</script>

<template>
  <Collapsible
    v-if="snapshot"
    class="min-w-0 max-w-full overflow-hidden rounded-2xl rounded-bl-md border border-border/50 bg-muted/40 text-sm"
  >
    <!-- Header -->
    <CollapsibleTrigger class="flex w-full items-center gap-2 px-4 py-2.5 text-left">
      <ListChecks
        class="size-4 shrink-0"
        :class="allDone ? 'text-emerald-500' : 'text-muted-foreground'"
      />
      <span class="shrink-0 text-sm font-medium">
        {{ allDone ? '任務完成' : '先前任務' }}
      </span>
      <span class="ml-auto flex items-center gap-2.5">
        <span class="hidden h-1.5 w-20 overflow-hidden rounded-full bg-muted sm:block">
          <span
            class="block h-full rounded-full transition-all"
            :class="allDone ? 'bg-emerald-500' : 'bg-primary'"
            :style="{
              width: snapshot.total > 0
                ? Math.round((snapshot.completed / snapshot.total) * 100) + '%'
                : '0%',
            }"
          />
        </span>
        <span class="shrink-0 text-xs tabular-nums text-muted-foreground">
          {{ snapshot.completed }}/{{ snapshot.total }}
        </span>
      </span>
      <ChevronDown
        class="ml-1 size-4 shrink-0 text-muted-foreground transition-transform [&[data-state=open]]:rotate-180"
      />
    </CollapsibleTrigger>

    <!-- Timeline body -->
    <CollapsibleContent class="border-t border-border/50 px-4 py-3">
      <ol class="relative">
        <li
          v-for="(t, i) in snapshot.todos"
          :key="i"
          class="relative flex gap-3 pb-3 last:pb-0"
        >
          <!-- Vertical connector line (not shown on last item) -->
          <div
            v-if="i < snapshot.todos.length - 1"
            class="absolute left-[7px] top-5 w-px"
            :class="t.status === 'completed' ? 'bg-emerald-500/40' : 'bg-border'"
            style="bottom: 0"
          />

          <!-- Status dot -->
          <div class="relative z-10 mt-0.5 shrink-0">
            <component
              :is="iconFor(t)"
              class="size-4"
              :class="iconClass(t)"
            />
          </div>

          <!-- Content -->
          <div class="min-w-0 flex-1 pt-0.5">
            <p
              class="text-sm leading-snug"
              :class="labelClass(t)"
            >
              {{ t.status === 'in_progress' ? t.activeForm : t.content }}
            </p>
          </div>
        </li>
      </ol>
    </CollapsibleContent>
  </Collapsible>
</template>

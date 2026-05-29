<script setup lang="ts">
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import type { AskUserQuestion, DisplayToolCall } from '@/lib/types'
import { useChatStore } from '@/stores/chat'
import { CircleCheck, HelpCircle, Loader2 } from 'lucide-vue-next'
import { computed, ref } from 'vue'

const props = defineProps<{
  toolCall: DisplayToolCall
  sessionId: string
}>()

const chat = useChatStore()
const submitting = ref(false)

const questions = computed<AskUserQuestion[]>(() => {
  const q = (props.toolCall.arguments as { questions?: unknown }).questions
  if (!Array.isArray(q)) return []
  return q as AskUserQuestion[]
})

// Track selected options per question index
const selections = ref<Map<number, Set<string>>>(new Map())

function getSelected(idx: number): Set<string> {
  if (!selections.value.has(idx)) {
    selections.value.set(idx, new Set())
  }
  return selections.value.get(idx)!
}

function toggle(questionIdx: number, label: string, multiSelect: boolean) {
  if (props.toolCall.status !== 'running') return
  const sel = getSelected(questionIdx)
  if (multiSelect) {
    if (sel.has(label)) sel.delete(label)
    else sel.add(label)
  } else {
    sel.clear()
    sel.add(label)
  }
  // Trigger reactivity
  selections.value = new Map(selections.value)
}

function isSelected(questionIdx: number, label: string): boolean {
  return getSelected(questionIdx).has(label)
}

const allAnswered = computed(() => {
  return questions.value.every((_, idx) => getSelected(idx).size > 0)
})

// Parse answers from tool result when completed. The result may arrive as an
// object (live stream) or as a JSON-serialised string (hydrated from history).
const completedAnswers = computed<Record<string, string | string[]> | null>(() => {
  if (props.toolCall.status !== 'ok') return null
  let result: unknown = props.toolCall.result
  if (typeof result === 'string') {
    try {
      result = JSON.parse(result)
    } catch {
      return null
    }
  }
  if (!result || typeof result !== 'object') return null
  const r = result as { ok?: boolean; answers?: Record<string, unknown> }
  if (!r.ok || !r.answers) return null
  return r.answers as Record<string, string | string[]>
})

async function submit() {
  if (!allAnswered.value || submitting.value) return
  const answers: Record<string, string | string[]> = {}
  for (const [idx, q] of questions.value.entries()) {
    const sel = [...getSelected(idx)]
    answers[q.question] = q.multiSelect ? sel : (sel[0] ?? '')
  }
  submitting.value = true
  try {
    await api.answerAskUserQuestion(props.sessionId, answers)
  } catch {
    // The agent will time out or the stream will error — let the existing
    // error handling surface it.
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <!-- Completed state -->
  <div
    v-if="toolCall.status === 'ok' && completedAnswers"
    class="min-w-0 max-w-full overflow-hidden rounded-2xl rounded-bl-md border border-border/50 bg-muted/50 text-sm"
  >
    <div class="flex items-center gap-2 px-4 py-2.5">
      <HelpCircle class="size-4 shrink-0 text-muted-foreground" />
      <CircleCheck class="size-4 shrink-0 text-emerald-500" />
      <span class="text-sm text-muted-foreground">已回答問題</span>
      <span class="ml-auto text-xs text-muted-foreground">
        {{ Object.keys(completedAnswers).length }} 題
      </span>
    </div>
    <div class="space-y-3 border-t border-border/50 px-4 py-3">
      <div
        v-for="(q, idx) in questions"
        :key="idx"
        class="space-y-1"
      >
        <div class="text-xs font-medium text-muted-foreground">{{ q.header }}</div>
        <div class="text-sm">{{ q.question }}</div>
        <div class="flex flex-wrap gap-1.5 pt-0.5">
          <template v-for="opt in q.options" :key="opt.label">
            <span
              v-if="Array.isArray(completedAnswers[q.question])
                ? (completedAnswers[q.question] as string[]).includes(opt.label)
                : completedAnswers[q.question] === opt.label"
              class="inline-flex items-center rounded-md border border-primary/40 bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary"
            >
              {{ opt.label }}
            </span>
          </template>
        </div>
      </div>
    </div>
  </div>

  <!-- Pending / running state -->
  <div
    v-else-if="toolCall.status === 'running'"
    class="min-w-0 max-w-full overflow-hidden rounded-2xl rounded-bl-md border border-primary/30 bg-background text-sm shadow-sm"
  >
    <div class="flex items-center gap-2 border-b border-border/50 px-4 py-2.5">
      <HelpCircle class="size-4 shrink-0 text-primary" />
      <Loader2 class="size-4 shrink-0 animate-spin text-muted-foreground" />
      <span class="text-sm font-medium">需要您的輸入</span>
    </div>

    <div class="space-y-5 px-4 py-4">
      <div
        v-for="(q, qIdx) in questions"
        :key="qIdx"
        class="space-y-2"
      >
        <div class="flex items-center gap-2">
          <span
            class="inline-flex items-center rounded-md bg-muted px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground"
          >
            {{ q.header }}
          </span>
          <span v-if="q.multiSelect" class="text-[10px] text-muted-foreground">（可多選）</span>
        </div>
        <div class="text-sm font-medium">{{ q.question }}</div>
        <div class="space-y-1.5">
          <button
            v-for="opt in q.options"
            :key="opt.label"
            type="button"
            class="w-full rounded-lg border px-3 py-2 text-left transition-colors"
            :class="isSelected(qIdx, opt.label)
              ? 'border-primary bg-primary/10 text-foreground'
              : 'border-border/60 bg-muted/30 text-foreground hover:border-border hover:bg-muted/60'"
            @click="toggle(qIdx, opt.label, q.multiSelect)"
          >
            <div class="flex items-start gap-2">
              <div
                class="mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border transition-colors"
                :class="isSelected(qIdx, opt.label)
                  ? 'border-primary bg-primary'
                  : 'border-muted-foreground/40'"
              >
                <div
                  v-if="isSelected(qIdx, opt.label)"
                  class="size-2 rounded-full bg-primary-foreground"
                />
              </div>
              <div class="min-w-0">
                <div class="text-sm font-medium leading-snug">{{ opt.label }}</div>
                <div class="mt-0.5 text-xs text-muted-foreground">{{ opt.description }}</div>
              </div>
            </div>
          </button>
        </div>
      </div>

      <Button
        class="w-full"
        :disabled="!allAnswered || submitting || chat.isStreaming === false"
        @click="submit"
      >
        <Loader2 v-if="submitting" class="mr-2 size-4 animate-spin" />
        提交回答
      </Button>
    </div>
  </div>

  <!-- Failed state -->
  <div
    v-else-if="toolCall.status === 'failed'"
    class="min-w-0 max-w-full overflow-hidden rounded-2xl rounded-bl-md border border-destructive/30 bg-muted/50 px-4 py-2.5 text-sm"
  >
    <div class="flex items-center gap-2">
      <HelpCircle class="size-4 shrink-0 text-muted-foreground" />
      <span class="text-xs text-destructive">問題回答失敗或逾時</span>
    </div>
  </div>
</template>

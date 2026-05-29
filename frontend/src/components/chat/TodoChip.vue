<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { onClickOutside } from '@vueuse/core'
import { useChatStore } from '@/stores/chat'
import {
  CheckCircle2,
  ChevronDown,
  Circle,
  CircleDot,
  Loader2,
  ListTodo,
} from 'lucide-vue-next'

const chat = useChatStore()
const { todos, todoStats, isStreaming } = storeToRefs(chat)

const visible = computed(() => todoStats.value.total > 0)

const allDone = computed(
  () => todoStats.value.total > 0 && todoStats.value.completed === todoStats.value.total,
)

const progressPct = computed(() => {
  const { completed, total } = todoStats.value
  return total > 0 ? Math.round((completed / total) * 100) : 0
})

const headline = computed(() => {
  if (allDone.value) return '全部完成'
  return todoStats.value.active?.activeForm ?? '任務清單'
})

// Popover -------------------------------------------------------------------
const open = ref(false)
const root = ref<HTMLElement | null>(null)
onClickOutside(root, () => {
  open.value = false
})

// Completion micro-interaction ---------------------------------------------
interface Particle {
  id: number
  left: number
  dx: number
  delay: number
  hue: number
  size: number
}
const particles = ref<Particle[]>([])
let particleSeq = 0
const celebrating = ref(false)
let celebrateTimer: number | null = null

function celebrate() {
  celebrating.value = true
  const next: Particle[] = []
  for (let i = 0; i < 14; i++) {
    next.push({
      id: particleSeq++,
      left: 10 + Math.random() * 80,
      dx: (Math.random() - 0.5) * 90,
      delay: Math.random() * 0.16,
      hue: Math.floor(Math.random() * 360),
      size: 4 + Math.random() * 5,
    })
  }
  particles.value = next
  window.setTimeout(() => {
    particles.value = []
  }, 1100)
  if (celebrateTimer !== null) window.clearTimeout(celebrateTimer)
  celebrateTimer = window.setTimeout(() => {
    celebrating.value = false
    celebrateTimer = null
  }, 1800)
}

watch(allDone, (done, was) => {
  if (done && !was) celebrate()
})

// Collapse the popover whenever the list is replaced by a new task.
watch(todos, () => {
  open.value = false
})

const STATUS_ICON = {
  completed: CheckCircle2,
  in_progress: CircleDot,
  pending: Circle,
} as const
</script>

<template>
  <div v-if="visible" ref="root" class="relative">
    <button
      type="button"
      class="relative flex max-w-xs items-center gap-2.5 overflow-hidden rounded-full border px-3.5 py-1.5 text-sm transition-colors hover:bg-muted"
      :class="celebrating ? 'border-emerald-400/60' : 'border-border/60'"
      :aria-label="`任務進度 ${todoStats.completed}/${todoStats.total}`"
      @click="open = !open"
    >
      <!-- Confetti layer -->
      <span
        v-for="p in particles"
        :key="p.id"
        class="todo-chip-confetti"
        :style="{
          left: p.left + '%',
          width: p.size + 'px',
          height: p.size + 'px',
          background: `hsl(${p.hue} 85% 60%)`,
          animationDelay: p.delay + 's',
          '--dx': p.dx + 'px',
        }"
      />

      <CheckCircle2
        v-if="allDone"
        class="size-4 shrink-0 text-emerald-500"
        :class="celebrating ? 'todo-pop' : ''"
      />
      <Loader2
        v-else-if="todoStats.active && isStreaming"
        class="size-4 shrink-0 animate-spin text-primary"
      />
      <ListTodo v-else class="size-4 shrink-0 text-muted-foreground" />

      <span class="hidden min-w-0 truncate font-medium sm:inline">
        {{ headline }}
      </span>
      <span class="hidden h-1.5 w-14 shrink-0 overflow-hidden rounded-full bg-muted md:block">
        <span
          class="block h-full rounded-full transition-all duration-500"
          :class="allDone ? 'bg-emerald-500' : 'bg-primary'"
          :style="{ width: progressPct + '%' }"
        />
      </span>
      <span class="shrink-0 tabular-nums text-muted-foreground">
        {{ todoStats.completed }}/{{ todoStats.total }}
      </span>
      <ChevronDown
        class="size-4 shrink-0 text-muted-foreground transition-transform"
        :class="open ? 'rotate-180' : ''"
      />
    </button>

    <!-- Dropdown list -->
    <Transition name="todo-pop-list">
      <div
        v-if="open"
        class="absolute right-0 bottom-full z-50 mb-2 max-h-96 w-96 overflow-auto rounded-xl border border-border/60 bg-background/95 p-4 shadow-xl backdrop-blur"
      >
        <ol class="relative">
          <li
            v-for="(t, i) in todos"
            :key="i"
            class="relative flex gap-3 pb-3 last:pb-0"
          >
            <!-- Vertical connector -->
            <div
              v-if="i < todos.length - 1"
              class="absolute left-[7px] top-5 w-px"
              :class="t.status === 'completed' ? 'bg-emerald-500/40' : 'bg-border'"
              style="bottom: 0"
            />

            <!-- Status icon -->
            <div class="relative z-10 mt-0.5 shrink-0">
              <Loader2
                v-if="t.status === 'in_progress'"
                class="size-4 animate-spin text-primary"
              />
              <component
                :is="STATUS_ICON[t.status]"
                v-else
                class="size-4"
                :class="t.status === 'completed' ? 'text-emerald-500' : 'text-muted-foreground/40'"
              />
            </div>

            <!-- Label -->
            <div class="min-w-0 flex-1 pt-0.5">
              <p
                class="text-sm leading-snug"
                :class="{
                  'text-muted-foreground line-through decoration-muted-foreground/30':
                    t.status === 'completed',
                  'font-medium text-foreground': t.status === 'in_progress',
                  'text-muted-foreground': t.status === 'pending',
                }"
              >
                {{ t.status === 'in_progress' ? t.activeForm : t.content }}
              </p>
            </div>
          </li>
        </ol>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.todo-pop-list-enter-active,
.todo-pop-list-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.todo-pop-list-enter-from,
.todo-pop-list-leave-to {
  opacity: 0;
  transform: translateY(6px);
}

@keyframes todo-chip-confetti-fall {
  0% {
    opacity: 1;
    transform: translate(0, 0) scale(1) rotate(0deg);
  }
  100% {
    opacity: 0;
    transform: translate(var(--dx), 34px) scale(0.4) rotate(200deg);
  }
}
.todo-chip-confetti {
  position: absolute;
  top: 50%;
  border-radius: 2px;
  pointer-events: none;
  animation: todo-chip-confetti-fall 0.9s ease-out forwards;
}

@keyframes todo-pop {
  0% {
    transform: scale(1);
  }
  40% {
    transform: scale(1.35);
  }
  100% {
    transform: scale(1);
  }
}
.todo-pop {
  animation: todo-pop 0.5s ease-out;
}

@media (prefers-reduced-motion: reduce) {
  .todo-chip-confetti {
    display: none;
  }
  .todo-pop {
    animation: none;
  }
}
</style>

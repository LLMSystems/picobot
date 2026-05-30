<script setup lang="ts">
// Sticky left rail that lists every dashboard section anchor.
// Active item is driven by an IntersectionObserver that tracks every visible
// section and picks the topmost one. A short "click lock" suspends updates
// while a programmatic smooth scroll is in flight, so the dot doesn't flicker
// across passing sections before reaching the target.
import { onBeforeUnmount, onMounted, ref, watch, type Component } from 'vue'
import {
  Activity,
  Cpu,
  TrendingUp,
  Gauge,
  ListFilter,
  Coins,
  FocusIcon,
} from 'lucide-vue-next'

export interface AnchorItem {
  id: string
  label: string
  icon: Component
}

const ANCHORS: AnchorItem[] = [
  { id: 'health', label: '系統健康總覽', icon: Activity },
  { id: 'resources', label: '系統 / Agent', icon: Cpu },
  { id: 'trends', label: '趨勢', icon: TrendingUp },
  { id: 'api-trends', label: 'API / 子代理', icon: Gauge },
  { id: 'lists', label: '熱門 / 活動', icon: ListFilter },
  { id: 'usage', label: 'Token 用量', icon: Coins },
  { id: 'session', label: 'Session 細項', icon: FocusIcon },
]

const props = defineProps<{ scrollContainer: HTMLElement | null }>()

const active = ref<string>(ANCHORS[0]!.id)
let observer: IntersectionObserver | null = null

// Live set of currently-intersecting sections, keyed by anchor id. Updated
// incrementally on each observer callback so a single callback never has to
// re-derive the full visibility state from one batch of entries.
const visible = new Map<string, IntersectionObserverEntry>()

// While the user is mid-click, suppress observer-driven updates so the
// in-flight smooth scroll doesn't flicker `active` across passing sections.
let clickLockTimer: number | null = null
let clickLocked = false

function lockForClick(ms: number = 700) {
  clickLocked = true
  if (clickLockTimer !== null) window.clearTimeout(clickLockTimer)
  clickLockTimer = window.setTimeout(() => {
    clickLocked = false
    clickLockTimer = null
    // After releasing, run one pass so active aligns with where we landed.
    recomputeActiveFromVisible()
  }, ms)
}

function recomputeActiveFromVisible() {
  // Pick the topmost visible section — the one whose top edge is closest
  // to (but ideally above) the viewport top. This matches how a reader
  // perceives "the section I'm currently in".
  let topmost: { id: string; top: number } | null = null
  for (const [id, entry] of visible) {
    const top = entry.boundingClientRect.top
    if (!topmost || top < topmost.top) {
      topmost = { id, top }
    }
  }
  if (topmost) active.value = topmost.id
}

function buildObserver(container: HTMLElement | null) {
  if (observer) {
    observer.disconnect()
    observer = null
  }
  visible.clear()
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        const id = (entry.target as HTMLElement).dataset.anchor
        if (!id) continue
        if (entry.isIntersecting) {
          visible.set(id, entry)
        } else {
          visible.delete(id)
        }
      }
      if (!clickLocked) recomputeActiveFromVisible()
    },
    {
      root: container,
      // Active band sits in the top portion of the viewport. The -85%
      // bottom margin shrinks the effective intersection zone to roughly
      // the top 15%, so at most one or two sections qualify as "the
      // currently active section" at any moment.
      rootMargin: '0px 0px -85% 0px',
      threshold: 0,
    },
  )
  for (const item of ANCHORS) {
    const el = (container ?? document).querySelector(
      `[data-anchor="${item.id}"]`,
    )
    if (el) observer.observe(el)
  }
}

function scrollTo(id: string) {
  // Set active immediately so the click feels instant, then lock observer
  // for ~700ms while the smooth scroll runs to completion.
  active.value = id
  lockForClick()
  const root = props.scrollContainer ?? document
  const el = root.querySelector(
    `[data-anchor="${id}"]`,
  ) as HTMLElement | null
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

onMounted(() => {
  requestAnimationFrame(() => buildObserver(props.scrollContainer))
})

watch(
  () => props.scrollContainer,
  (container) => {
    if (container) requestAnimationFrame(() => buildObserver(container))
  },
)

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
  if (clickLockTimer !== null) window.clearTimeout(clickLockTimer)
})

defineExpose({ rebuild: () => buildObserver(props.scrollContainer) })
</script>

<template>
  <nav class="flex h-full w-[200px] shrink-0 flex-col gap-1 border-r bg-background px-3 py-4">
    <div class="px-2 pb-2 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
      Dashboard
    </div>
    <button
      v-for="item in ANCHORS"
      :key="item.id"
      type="button"
      class="group flex items-center gap-2 rounded-md px-2 py-1.5 text-xs font-medium transition-colors"
      :class="active === item.id
        ? 'bg-muted text-foreground'
        : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground'"
      @click="scrollTo(item.id)"
    >
      <span
        class="size-1 rounded-full"
        :class="active === item.id ? 'bg-primary' : 'bg-transparent'"
        aria-hidden="true"
      />
      <component :is="item.icon" class="size-3.5" />
      <span class="truncate">{{ item.label }}</span>
    </button>
  </nav>
</template>

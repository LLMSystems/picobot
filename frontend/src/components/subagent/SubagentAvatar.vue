<script setup lang="ts">
import { computed } from 'vue'
import { Bot } from 'lucide-vue-next'

const props = defineProps<{
  taskId: string
  size?: 'sm' | 'md'
  running?: boolean
}>()

// Deterministic hue (0–359) from task_id, so the same subagent always
// gets the same accent color.
function hashHue(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) {
    h = (h * 31 + s.charCodeAt(i)) & 0xffffffff
  }
  return Math.abs(h) % 360
}

const hue = computed(() => hashHue(props.taskId))

const style = computed(() => ({
  background: `linear-gradient(135deg, hsl(${hue.value} 70% 60% / 0.22), hsl(${
    (hue.value + 40) % 360
  } 70% 50% / 0.32))`,
  color: `hsl(${hue.value} 70% 35%)`,
  borderColor: `hsl(${hue.value} 70% 55% / 0.45)`,
}))

const sizeClass = computed(() =>
  props.size === 'md' ? 'size-9' : 'size-7',
)
const iconSize = computed(() => (props.size === 'md' ? 'size-5' : 'size-4'))
</script>

<template>
  <span
    class="relative inline-flex shrink-0 items-center justify-center rounded-md border"
    :class="sizeClass"
    :style="style"
  >
    <Bot :class="iconSize" />
    <span
      v-if="running"
      class="absolute -right-0.5 -top-0.5 inline-flex size-2 items-center justify-center"
    >
      <span class="absolute inline-flex size-2 animate-ping rounded-full bg-amber-400 opacity-60" />
      <span class="relative inline-flex size-1.5 rounded-full bg-amber-500" />
    </span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import PicobotIcon from '@/components/common/PicobotIcon.vue'

const props = defineProps<{
  taskId: string
  size?: 'sm' | 'md'
  running?: boolean
}>()

// Deterministic hue from task_id, so the same subagent always gets the same
// accent color. Used for the container gradient (not the bot's body) so the
// bot character stays recognizable while each subagent has a unique frame.
function hashHue(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) {
    h = (h * 31 + s.charCodeAt(i)) & 0xffffffff
  }
  return Math.abs(h) % 360
}

const hue = computed(() => hashHue(props.taskId))

const containerStyle = computed(() => ({
  background: `linear-gradient(135deg, hsl(${hue.value} 70% 60% / 0.18), hsl(${
    (hue.value + 40) % 360
  } 70% 50% / 0.28))`,
  borderColor: `hsl(${hue.value} 70% 55% / 0.4)`,
}))

const sizeClass = computed(() =>
  props.size === 'md' ? 'size-9' : 'size-7',
)

// Picobot image sits slightly inset so the container gradient frames it.
const iconPx = computed(() => (props.size === 'md' ? 28 : 22))

const state = computed<'running' | 'idle'>(() =>
  props.running ? 'running' : 'idle',
)
</script>

<template>
  <span
    class="relative inline-flex shrink-0 items-center justify-center rounded-md border"
    :class="sizeClass"
    :style="containerStyle"
  >
    <PicobotIcon :size="iconPx" :state="state" />
    <span
      v-if="running"
      class="absolute -right-0.5 -top-0.5 inline-flex size-2 items-center justify-center"
    >
      <span
        class="absolute inline-flex size-2 animate-ping rounded-full bg-amber-400 opacity-60"
      />
      <span class="relative inline-flex size-1.5 rounded-full bg-amber-500" />
    </span>
  </span>
</template>

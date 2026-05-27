<script setup lang="ts">
import { computed } from 'vue'
import picobotImg from '@/assets/picoagent_for_subagent.png'

type PicobotState =
  | 'idle'
  | 'running'
  | 'thinking'
  | 'done'
  | 'failed'
  | 'sleeping'

type PicobotSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl'

const props = withDefaults(
  defineProps<{
    size?: PicobotSize | number
    state?: PicobotState
    ring?: boolean
    glow?: boolean
    hue?: number // 0–360, optional hue-rotate filter for per-instance tinting
  }>(),
  {
    size: 'md',
    state: 'idle',
    ring: false,
    glow: false,
  },
)

const SIZE_MAP: Record<PicobotSize, number> = {
  xs: 16,
  sm: 24,
  md: 32,
  lg: 48,
  xl: 96,
}

const px = computed(() =>
  typeof props.size === 'number' ? props.size : SIZE_MAP[props.size],
)

const ringColor = computed(() => {
  switch (props.state) {
    case 'running':
    case 'thinking':
      return 'rgb(245 158 11 / 0.5)' // amber
    case 'done':
      return 'rgb(16 185 129 / 0.5)' // emerald
    case 'failed':
      return 'rgb(239 68 68 / 0.55)' // red
    default:
      return 'transparent'
  }
})

const wrapperClass = computed(() => {
  const out = ['relative inline-flex shrink-0 items-center justify-center']
  if (props.state === 'failed') out.push('rotate-[-3deg]')
  return out
})

const wrapperStyle = computed(() => {
  const style: Record<string, string> = {
    width: `${px.value}px`,
    height: `${px.value}px`,
  }
  if (props.ring) {
    style.borderRadius = '9999px'
    style.boxShadow = `0 0 0 2px ${ringColor.value}`
  }
  return style
})

const imgClass = computed(() => {
  const out = ['select-none']
  if (props.state === 'running') out.push('picobot-pulse')
  else if (props.state === 'thinking') out.push('picobot-wobble')
  return out
})

const imgStyle = computed(() => {
  const filters: string[] = []
  if (props.hue !== undefined) filters.push(`hue-rotate(${props.hue}deg)`)
  if (props.state === 'sleeping') {
    filters.push('grayscale(0.7)', 'opacity(0.55)')
  }
  if (props.glow) {
    filters.push(`drop-shadow(0 0 6px ${ringColor.value})`)
  }
  return filters.length > 0 ? { filter: filters.join(' ') } : undefined
})
</script>

<template>
  <span :class="wrapperClass" :style="wrapperStyle">
    <img
      :src="picobotImg"
      :width="px"
      :height="px"
      :class="imgClass"
      :style="imgStyle"
      alt="Picobot"
      draggable="false"
    />
  </span>
</template>

<style scoped>
@keyframes picobot-pulse {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.06);
  }
}

.picobot-pulse {
  animation: picobot-pulse 1.4s ease-in-out infinite;
}

@keyframes picobot-wobble {
  0%,
  100% {
    transform: rotate(-3deg);
  }
  50% {
    transform: rotate(3deg);
  }
}

.picobot-wobble {
  animation: picobot-wobble 1.6s ease-in-out infinite;
}
</style>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

// 動畫素材：每個 variant 有「動畫 webp」與「靜態幀 png」兩份。
// 活躍狀態播動畫、靜止狀態（或使用者偏好減少動態）退回靜態幀。
import idleAnim from '@/assets/idle/transparent_backup.webp'
import idleStatic from '@/assets/idle/source_static.png'
import subagentAnim from '@/assets/subagent/transparent_backup.webp'
import subagentStatic from '@/assets/subagent/source_static.png'

type PicobotState =
  | 'idle'
  | 'running'
  | 'thinking'
  | 'done'
  | 'failed'
  | 'sleeping'

type PicobotSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl'

// 外觀：決定用哪一組素材。idle = 主 agent / 一般情境，subagent = 子代理情境。
type PicobotVariant = 'idle' | 'subagent'

const props = withDefaults(
  defineProps<{
    size?: PicobotSize | number
    state?: PicobotState
    variant?: PicobotVariant
    ring?: boolean
    glow?: boolean
    hue?: number // 0–360, optional hue-rotate filter for per-instance tinting
  }>(),
  {
    size: 'md',
    state: 'idle',
    variant: 'idle',
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

const SOURCES: Record<PicobotVariant, { anim: string; still: string }> = {
  idle: { anim: idleAnim, still: idleStatic },
  subagent: { anim: subagentAnim, still: subagentStatic },
}

// 會播放動畫的狀態；其餘（done / failed / sleeping）顯示靜態幀。
const ANIMATED_STATES = new Set<PicobotState>(['idle', 'running', 'thinking'])

// 尊重 prefers-reduced-motion：偏好減少動態時一律靜態。
const prefersReducedMotion = ref(false)
let mq: MediaQueryList | null = null
const syncReducedMotion = () => {
  prefersReducedMotion.value = mq?.matches ?? false
}
onMounted(() => {
  if (typeof window !== 'undefined' && window.matchMedia) {
    mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    syncReducedMotion()
    mq.addEventListener('change', syncReducedMotion)
  }
})
onUnmounted(() => {
  mq?.removeEventListener('change', syncReducedMotion)
})

const px = computed(() =>
  typeof props.size === 'number' ? props.size : SIZE_MAP[props.size],
)

const shouldAnimate = computed(
  () => !prefersReducedMotion.value && ANIMATED_STATES.has(props.state),
)

const imgSrc = computed(() => {
  const set = SOURCES[props.variant]
  return shouldAnimate.value ? set.anim : set.still
})

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
  // CSS 動態僅在允許動畫時疊加，避免與 reduced-motion 衝突。
  if (!prefersReducedMotion.value) {
    if (props.state === 'running') out.push('picobot-pulse')
    else if (props.state === 'thinking') out.push('picobot-wobble')
  }
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
      :src="imgSrc"
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

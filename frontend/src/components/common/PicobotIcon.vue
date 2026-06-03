<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

// 動畫素材：每組動作有「動畫 webp」與「靜態幀 png」兩份。
// 活躍狀態播動畫、靜止狀態（或使用者偏好減少動態）退回靜態幀。
import idleAnim from '@/assets/idle/transparent_backup.webp'
import idleStatic from '@/assets/idle/source_static.png'
import runningAnim from '@/assets/running/transparent_backup.webp'
import runningStatic from '@/assets/running/source_static.png'
import workingAnim from '@/assets/working/transparent_backup.webp'
import workingStatic from '@/assets/working/source_static.png'
import dashboardAnim from '@/assets/dashboard/transparent_backup.webp'
import dashboardStatic from '@/assets/dashboard/source_static.png'

type PicobotState =
  | 'idle'
  | 'running'
  | 'thinking'
  | 'done'
  | 'failed'
  | 'sleeping'

type PicobotSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl'

// 使用情境：idle = 主 agent / 一般情境，subagent = 子代理，security = 安全/儀表板。
type PicobotVariant = 'idle' | 'subagent' | 'security'

// 實際素材組（動作別）。情境與狀態最終都收斂成這四組其中一組。
type PicobotArt = 'idle' | 'running' | 'working' | 'dashboard'

// ring/glow 顏色語意，可由外部直接指定（與 state 解耦）。
type PicobotTone = 'amber' | 'emerald' | 'red'

const props = withDefaults(
  defineProps<{
    size?: PicobotSize | number
    state?: PicobotState
    variant?: PicobotVariant
    ring?: boolean
    glow?: boolean
    // 直接指定 ring/glow 顏色，與 state 解耦（讓 icon 可維持動畫但顯示任意色）。
    tone?: PicobotTone
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

const SOURCES: Record<PicobotArt, { anim: string; still: string }> = {
  idle: { anim: idleAnim, still: idleStatic },
  running: { anim: runningAnim, still: runningStatic },
  working: { anim: workingAnim, still: workingStatic },
  dashboard: { anim: dashboardAnim, still: dashboardStatic },
}

// 各素材原圖的透明邊距不一，置中放大以抵銷留白（1 = 不縮放）。
// idle 內容僅約佔畫面 40%×60%，放大約 1.4 倍可貼近邊緣。
const ART_SCALE: Partial<Record<PicobotArt, number>> = {
  idle: 1.4, // 內容約佔 40%×60%（窄高）
  running: 1.25, // 內容約佔 58%×74%（窄高）
  working: 1.2, // 內容約佔 77%×59%（寬扁），放太多會橫向爆出
  dashboard: 1.15, // 內容約佔 77%×81%，本來就填得滿，小幅即可
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

// 情境覆寫優先：security → dashboard 素材、subagent → working 素材。
// 主 agent（idle 情境）則依 state 選圖：
//   idle→idle、running→running、thinking/done→working、failed/sleeping→idle。
const artSet = computed<PicobotArt>(() => {
  if (props.variant === 'security') return 'dashboard'
  if (props.variant === 'subagent') return 'working'
  switch (props.state) {
    case 'running':
      return 'running'
    case 'thinking':
    case 'done':
      return 'working'
    default:
      return 'idle'
  }
})

const imgSrc = computed(() => {
  const set = SOURCES[artSet.value]
  return shouldAnimate.value ? set.anim : set.still
})

const TONE_COLORS: Record<PicobotTone, string> = {
  amber: 'rgb(245 158 11 / 0.5)',
  emerald: 'rgb(16 185 129 / 0.5)',
  red: 'rgb(239 68 68 / 0.55)',
}

const ringColor = computed(() => {
  // tone 優先：可在維持動畫狀態下指定任意光暈顏色。
  if (props.tone) return TONE_COLORS[props.tone]
  switch (props.state) {
    case 'running':
    case 'thinking':
      return TONE_COLORS.amber
    case 'done':
      return TONE_COLORS.emerald
    case 'failed':
      return TONE_COLORS.red
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
  // picobot-img 提供基礎 transform: scale(var(--picobot-scale))。
  const out = ['select-none', 'picobot-img']
  // CSS 動態僅在允許動畫時疊加，避免與 reduced-motion 衝突。
  if (!prefersReducedMotion.value) {
    if (props.state === 'running') out.push('picobot-pulse')
    else if (props.state === 'thinking') out.push('picobot-wobble')
  }
  return out
})

const imgStyle = computed(() => {
  const style: Record<string, string> = {}
  const filters: string[] = []
  if (props.hue !== undefined) filters.push(`hue-rotate(${props.hue}deg)`)
  if (props.state === 'sleeping') {
    filters.push('grayscale(0.7)', 'opacity(0.55)')
  }
  if (props.glow) {
    filters.push(`drop-shadow(0 0 6px ${ringColor.value})`)
  }
  if (filters.length > 0) style.filter = filters.join(' ')
  // 部分素材的原圖含大量透明邊距（如 idle 內容僅約佔畫面 40%×60%）。
  // 置中放大畫面內容以抵銷留白；layout 尺寸不變（transform 不影響排版）。
  // 透過 CSS 變數讓縮放與 pulse/wobble 動畫的 transform 一起疊加。
  const scale = ART_SCALE[artSet.value]
  if (scale) style['--picobot-scale'] = String(scale)
  return Object.keys(style).length > 0 ? style : undefined
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
/* 基礎縮放：抵銷素材透明邊距。--picobot-scale 由元件依素材設定（預設 1）。 */
.picobot-img {
  transform: scale(var(--picobot-scale, 1));
}

/* 動畫的 transform 需把基礎縮放一起帶入，否則會覆蓋掉縮放。 */
@keyframes picobot-pulse {
  0%,
  100% {
    transform: scale(var(--picobot-scale, 1));
  }
  50% {
    transform: scale(calc(var(--picobot-scale, 1) * 1.06));
  }
}

.picobot-pulse {
  animation: picobot-pulse 1.4s ease-in-out infinite;
}

@keyframes picobot-wobble {
  0%,
  100% {
    transform: scale(var(--picobot-scale, 1)) rotate(-3deg);
  }
  50% {
    transform: scale(var(--picobot-scale, 1)) rotate(3deg);
  }
}

.picobot-wobble {
  animation: picobot-wobble 1.6s ease-in-out infinite;
}
</style>

<script setup lang="ts">
import { computed } from 'vue'
import PicobotIcon from '@/components/common/PicobotIcon.vue'

const props = defineProps<{
  taskId: string
  size?: 'xs' | 'sm' | 'md'
  running?: boolean
}>()

// 不再用容器框，icon 直接放大佔滿空間。
const iconPx = computed(() =>
  props.size === 'md' ? 90 : props.size === 'xs' ? 44 : 78,
)

const state = computed<'running' | 'idle'>(() =>
  props.running ? 'running' : 'idle',
)
</script>

<template>
  <span class="relative inline-flex shrink-0 items-center justify-center">
    <PicobotIcon :size="iconPx" :state="state" variant="subagent" />
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

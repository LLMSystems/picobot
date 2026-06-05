<script setup lang="ts">
import { computed } from 'vue'
import { personaIcon } from '@/lib/agentTypes'

const props = withDefaults(
  defineProps<{
    name?: string | null
    size?: number
    rounded?: boolean
  }>(),
  {
    name: null,
    size: 24,
    rounded: true,
  },
)

const src = computed(() => personaIcon(props.name))
const boxStyle = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
}))
</script>

<template>
  <span
    class="relative inline-flex shrink-0 items-center justify-center overflow-hidden"
    :class="rounded ? 'rounded-lg bg-muted/60' : ''"
    :style="boxStyle"
  >
    <img
      :src="src"
      alt=""
      aria-hidden="true"
      draggable="false"
      class="h-full w-full select-none object-contain"
    />
  </span>
</template>

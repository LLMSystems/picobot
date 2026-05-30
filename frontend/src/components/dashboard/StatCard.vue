<script setup lang="ts">
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { computed, type Component } from 'vue';
import { accent, type AccentColor } from './colors';

const props = defineProps<{
  label: string
  value: string | number | null | undefined
  hint?: string
  loading?: boolean
  icon?: Component
  color?: AccentColor
  /** Compact variant — tighter padding, smaller icon + value font.
   *  Use for dense rows of small metrics (e.g. system resources). */
  compact?: boolean
}>()

const display = computed(() => {
  if (props.loading) return null
  if (props.value === null || props.value === undefined || props.value === '') {
    return '—'
  }
  return String(props.value)
})

const tint = computed(() => (props.color ? accent(props.color) : null))
</script>

<template>
  <Card class="border-border/60 shadow-none" :class="compact ? '' : 'min-h-[140px]'">
    <CardContent
      class="flex flex-1 items-center gap-3"
      :class="compact ? 'px-3 py-2.5' : 'px-4 py-3'"
    >
      <div
        v-if="icon && tint"
        class="flex shrink-0 items-center justify-center rounded-lg"
        :class="[
          compact ? 'size-8' : 'size-10',
          tint.iconBg,
        ]"
      >
        <component
          :is="icon"
          :class="[compact ? 'size-4' : 'size-5', tint.iconText]"
        />
      </div>
      <div class="flex min-w-0 flex-1 flex-col gap-0.5">
        <div
          class="truncate font-medium uppercase tracking-wide text-muted-foreground"
          :class="compact ? 'text-xs' : 'text-xs'"
        >
          {{ label }}
        </div>
        <div
          class="font-semibold leading-tight truncate"
          :class="compact ? 'text-base' : 'text-2xl'"
        >
          <Skeleton v-if="loading" class="h-6 w-16" />
          <template v-else>{{ display }}</template>
        </div>
        <div
          v-if="hint"
          class="text-muted-foreground truncate"
          :class="compact ? 'text-[10px]' : 'text-xs'"
        >
          {{ hint }}
        </div>
      </div>
    </CardContent>
  </Card>
</template>

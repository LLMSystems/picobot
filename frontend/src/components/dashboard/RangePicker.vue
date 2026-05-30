<script setup lang="ts">
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { MetricsRange } from '@/lib/types'

const props = defineProps<{ modelValue: MetricsRange }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: MetricsRange): void }>()

const ranges: MetricsRange[] = ['1h', '24h', '7d']

function onUpdate(v: string | number) {
  emit('update:modelValue', v as MetricsRange)
}
</script>

<template>
  <Tabs :model-value="modelValue" @update:model-value="onUpdate">
    <TabsList class="h-8">
      <TabsTrigger
        v-for="r in ranges"
        :key="r"
        :value="r"
        class="h-7 px-3 text-xs"
      >
        {{ r }}
      </TabsTrigger>
    </TabsList>
  </Tabs>
</template>

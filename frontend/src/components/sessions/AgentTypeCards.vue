<script setup lang="ts">
import { onMounted } from 'vue'
import { useAgentTypesStore } from '@/stores/agentTypes'
import AgentTypeAvatar from '@/components/common/AgentTypeAvatar.vue'

withDefaults(
  defineProps<{
    busy?: boolean
    selected?: string | null
  }>(),
  { busy: false, selected: null },
)

const emit = defineEmits<{ (e: 'select', name: string): void }>()

const agentTypes = useAgentTypesStore()

onMounted(() => {
  void agentTypes.load()
})
</script>

<template>
  <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
    <button
      v-for="t in agentTypes.list"
      :key="t.name"
      type="button"
      :disabled="busy"
      class="group flex items-start gap-3 rounded-xl border bg-card p-4 text-left shadow-card transition-all duration-200 hover:-translate-y-px hover:border-brand hover:shadow-card-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-60"
      :class="
        selected === t.name ? 'border-brand ring-1 ring-brand/20' : ''
      "
      @click="emit('select', t.name)"
    >
      <AgentTypeAvatar :name="t.name" :size="48" />
      <span class="min-w-0 flex-1">
        <span class="block truncate text-sm font-medium leading-tight">
          {{ t.display_name }}
        </span>
        <span class="mt-1 block text-xs leading-relaxed text-muted-foreground">
          {{ t.description }}
        </span>
      </span>
    </button>
  </div>
</template>

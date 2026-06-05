import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/lib/api'
import type { AgentType } from '@/lib/types'

export const useAgentTypesStore = defineStore('agentTypes', () => {
  const list = ref<AgentType[]>([])
  const defaultName = ref<string>('default')
  const loaded = ref(false)
  const loading = ref(false)

  async function load() {
    if (loaded.value || loading.value) return
    loading.value = true
    try {
      const res = await api.agentTypes()
      list.value = res.agent_types
      defaultName.value = res.default
      loaded.value = true
    } catch {
      list.value = []
    } finally {
      loading.value = false
    }
  }

  const byName = computed(() => {
    const map = new Map<string, AgentType>()
    for (const t of list.value) map.set(t.name, t)
    return map
  })

  function find(name: string | null | undefined): AgentType | undefined {
    if (!name) return undefined
    return byName.value.get(name)
  }

  return { list, defaultName, loaded, loading, load, byName, find }
})

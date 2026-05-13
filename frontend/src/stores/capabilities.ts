import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/lib/api'
import type { Capabilities, ToolCapability } from '@/lib/types'

const FALLBACK: Capabilities = {
  model: { provider: 'unknown', name: 'unknown' },
  max_iterations: 8,
  tools: [],
  features: {
    streaming: true,
    session_workspace: false,
    file_upload: false,
    multimodal: false,
  },
}

export const useCapabilitiesStore = defineStore('capabilities', () => {
  const data = ref<Capabilities>(FALLBACK)
  const loaded = ref(false)
  const failed = ref(false)

  async function load() {
    if (loaded.value) return
    try {
      data.value = await api.capabilities()
      failed.value = false
    } catch {
      data.value = FALLBACK
      failed.value = true
    } finally {
      loaded.value = true
    }
  }

  const toolMap = computed(() => {
    const map = new Map<string, ToolCapability>()
    for (const t of data.value.tools) map.set(t.name, t)
    return map
  })

  const modelName = computed(() => data.value.model.name)
  const streamingEnabled = computed(() => data.value.features.streaming)

  return { data, loaded, failed, load, toolMap, modelName, streamingEnabled }
})

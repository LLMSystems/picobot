import { computed, ref, watch } from 'vue'
import { useCapabilitiesStore } from '@/stores/capabilities'

const STORAGE_KEY = 'picobot:selected_model'

function readStored(): string | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    return v && v.length > 0 ? v : null
  } catch {
    return null
  }
}

function writeStored(value: string | null) {
  try {
    if (value === null) localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, value)
  } catch {
    // ignore
  }
}

const selected = ref<string | null>(readStored())

export function useSelectedModel() {
  const caps = useCapabilitiesStore()

  watch(
    () => caps.data.available_models,
    (models) => {
      if (selected.value && !models.includes(selected.value)) {
        selected.value = null
        writeStored(null)
      }
    },
    { immediate: true },
  )

  const defaultModel = computed(() => caps.data.model.name)
  const availableModels = computed(() =>
    caps.data.available_models.filter((m) => m !== defaultModel.value),
  )

  const enabled = computed(
    () =>
      caps.data.features.model_override && availableModels.value.length > 0,
  )

  const effectiveModel = computed(
    () => selected.value ?? defaultModel.value,
  )

  const isDefault = computed(() => selected.value === null)

  function setSelected(model: string | null) {
    selected.value = model
    writeStored(model)
  }

  function resetToDefault() {
    setSelected(null)
  }

  return {
    selected,
    enabled,
    defaultModel,
    availableModels,
    effectiveModel,
    isDefault,
    setSelected,
    resetToDefault,
  }
}

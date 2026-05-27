import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import type { ChatOverrides } from '@/lib/types'

const STORAGE_KEY = 'picobot.settings.v1'

interface PersistedSettings {
  systemPrompt: string | null
  temperature: number | null
  maxTokens: number | null
  maxIterations: number | null
  disabledTools: string[]
}

const EMPTY: PersistedSettings = {
  systemPrompt: null,
  temperature: null,
  maxTokens: null,
  maxIterations: null,
  disabledTools: [],
}

function load(): PersistedSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...EMPTY }
    const parsed = JSON.parse(raw) as Partial<PersistedSettings>
    return {
      systemPrompt:
        typeof parsed.systemPrompt === 'string' ? parsed.systemPrompt : null,
      temperature:
        typeof parsed.temperature === 'number' ? parsed.temperature : null,
      maxTokens:
        typeof parsed.maxTokens === 'number' ? parsed.maxTokens : null,
      maxIterations:
        typeof parsed.maxIterations === 'number' ? parsed.maxIterations : null,
      disabledTools: Array.isArray(parsed.disabledTools)
        ? parsed.disabledTools.filter((x): x is string => typeof x === 'string')
        : [],
    }
  } catch {
    return { ...EMPTY }
  }
}

export const useSettingsStore = defineStore('settings', () => {
  const initial = load()
  const systemPrompt = ref<string | null>(initial.systemPrompt)
  const temperature = ref<number | null>(initial.temperature)
  const maxTokens = ref<number | null>(initial.maxTokens)
  const maxIterations = ref<number | null>(initial.maxIterations)
  const disabledTools = ref<string[]>(initial.disabledTools)

  watch(
    [systemPrompt, temperature, maxTokens, maxIterations, disabledTools],
    () => {
      const payload: PersistedSettings = {
        systemPrompt: systemPrompt.value,
        temperature: temperature.value,
        maxTokens: maxTokens.value,
        maxIterations: maxIterations.value,
        disabledTools: [...disabledTools.value],
      }
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
      } catch {
        // ignore quota / privacy mode errors
      }
    },
    { deep: true },
  )

  const chatOverrides = computed<ChatOverrides>(() => {
    const out: ChatOverrides = {}
    if (systemPrompt.value !== null && systemPrompt.value.trim() !== '') {
      out.system_prompt = systemPrompt.value
    }
    if (temperature.value !== null) out.temperature = temperature.value
    if (maxTokens.value !== null) out.max_tokens = maxTokens.value
    if (maxIterations.value !== null) out.max_iterations = maxIterations.value
    if (disabledTools.value.length > 0) {
      out.disabled_tools = [...disabledTools.value]
    }
    return out
  })

  const hasOverrides = computed(() => {
    return (
      systemPrompt.value !== null ||
      temperature.value !== null ||
      maxTokens.value !== null ||
      maxIterations.value !== null ||
      disabledTools.value.length > 0
    )
  })

  function setToolEnabled(name: string, enabled: boolean) {
    const idx = disabledTools.value.indexOf(name)
    if (enabled && idx >= 0) {
      disabledTools.value.splice(idx, 1)
    } else if (!enabled && idx < 0) {
      disabledTools.value.push(name)
    }
  }

  function isToolEnabled(name: string): boolean {
    return !disabledTools.value.includes(name)
  }

  function resetAll() {
    systemPrompt.value = null
    temperature.value = null
    maxTokens.value = null
    maxIterations.value = null
    disabledTools.value = []
  }

  return {
    systemPrompt,
    temperature,
    maxTokens,
    maxIterations,
    disabledTools,
    chatOverrides,
    hasOverrides,
    setToolEnabled,
    isToolEnabled,
    resetAll,
  }
})

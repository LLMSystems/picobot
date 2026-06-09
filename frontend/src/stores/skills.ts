import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/lib/api'
import type { SkillInfo } from '@/lib/types'

export const useSkillsStore = defineStore('skills', () => {
  const skills = ref<SkillInfo[]>([])
  const loaded = ref(false)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function refresh() {
    loading.value = true
    error.value = null
    try {
      const res = await api.listSkills()
      skills.value = res.skills
      loaded.value = true
    } catch (e) {
      error.value = e instanceof Error ? e.message : '載入 skills 失敗'
    } finally {
      loading.value = false
    }
  }

  async function load() {
    if (loaded.value) return
    await refresh()
  }

  async function create(
    name: string,
    content: string,
    files?: { path: string; content_base64: string }[],
  ) {
    await api.createSkill({ name, content, files })
    await refresh()
  }

  async function remove(name: string) {
    await api.deleteSkill(name)
    await refresh()
  }

  async function setDisabled(name: string, disabled: boolean) {
    // optimistic update
    const target = skills.value.find((s) => s.name === name)
    if (target) target.disabled = disabled
    try {
      await api.setSkillDisabled(name, disabled)
    } catch (e) {
      if (target) target.disabled = !disabled
      throw e
    }
  }

  const customSkills = computed(() => skills.value.filter((s) => s.source === 'custom'))
  // builtin + shared (legacy global) are both read-only, shown together.
  const builtinSkills = computed(() => skills.value.filter((s) => s.source !== 'custom'))
  const enabledCount = computed(() => skills.value.filter((s) => !s.disabled).length)

  return {
    skills,
    loaded,
    loading,
    error,
    refresh,
    load,
    create,
    remove,
    setDisabled,
    customSkills,
    builtinSkills,
    enabledCount,
  }
})

import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/lib/api'
import type { SessionSummary } from '@/lib/types'

function sortByUpdatedDesc(list: SessionSummary[]): SessionSummary[] {
  return [...list].sort((a, b) => b.updated_at.localeCompare(a.updated_at))
}

export const useSessionsStore = defineStore('sessions', () => {
  const list = ref<SessionSummary[]>([])
  const loading = ref(false)
  const loaded = ref(false)
  const error = ref<string | null>(null)

  async function fetchAll() {
    loading.value = true
    error.value = null
    try {
      const { sessions } = await api.listSessions()
      list.value = sortByUpdatedDesc(sessions)
      loaded.value = true
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  async function create(title?: string): Promise<SessionSummary> {
    const created = await api.createSession(title ? { title } : {})
    list.value = sortByUpdatedDesc([created, ...list.value])
    return created
  }

  async function rename(id: string, title: string) {
    const idx = list.value.findIndex((s) => s.session_id === id)
    if (idx < 0) return
    const prev = list.value[idx]!
    const optimistic: SessionSummary = { ...prev, title }
    list.value.splice(idx, 1, optimistic)
    try {
      const updated = await api.renameSession(id, title)
      const newIdx = list.value.findIndex((s) => s.session_id === id)
      if (newIdx >= 0) list.value.splice(newIdx, 1, updated)
    } catch (e) {
      const newIdx = list.value.findIndex((s) => s.session_id === id)
      if (newIdx >= 0) list.value.splice(newIdx, 1, prev)
      throw e
    }
  }

  async function remove(id: string) {
    const idx = list.value.findIndex((s) => s.session_id === id)
    if (idx < 0) return
    const prev = list.value[idx]!
    list.value.splice(idx, 1)
    try {
      await api.deleteSession(id)
    } catch (e) {
      list.value.splice(idx, 0, prev)
      throw e
    }
  }

  function findById(id: string | null | undefined): SessionSummary | undefined {
    if (!id) return undefined
    return list.value.find((s) => s.session_id === id)
  }

  function touchAfterSend(
    id: string,
    preview: { user: string; assistant: string },
  ) {
    const idx = list.value.findIndex((s) => s.session_id === id)
    if (idx < 0) return
    const s = list.value[idx]!
    const next: SessionSummary = {
      ...s,
      updated_at: new Date().toISOString(),
      last_user_message: preview.user,
      last_assistant_preview: preview.assistant,
      message_count: s.message_count + 2,
      title:
        s.title && s.title !== 'New Chat'
          ? s.title
          : preview.user.slice(0, 30) || s.title,
    }
    list.value.splice(idx, 1, next)
    list.value = sortByUpdatedDesc(list.value)
  }

  const newestId = computed<string | null>(
    () => list.value[0]?.session_id ?? null,
  )

  return {
    list,
    loading,
    loaded,
    error,
    fetchAll,
    create,
    rename,
    remove,
    findById,
    touchAfterSend,
    newestId,
  }
})

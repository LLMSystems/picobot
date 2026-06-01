import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/lib/api'
import { ApiError } from '@/lib/errors'
import type {
  SessionMemoryNoteKind,
  SessionMemoryResponse,
} from '@/lib/types'

export const useSessionMemoryStore = defineStore('sessionMemory', () => {
  const sessionId = ref<string | null>(null)
  const data = ref<SessionMemoryResponse | null>(null)
  const loading = ref(false)
  const lastError = ref<ApiError | null>(null)
  const savingNote = ref(false)
  const clearingSummary = ref(false)
  const deletingNoteId = ref<number | null>(null)

  async function refresh(id: string | null = sessionId.value): Promise<void> {
    sessionId.value = id
    lastError.value = null
    if (!id) {
      data.value = null
      return
    }
    loading.value = true
    try {
      data.value = await api.getSessionMemory(id)
    } catch (err) {
      if (err instanceof ApiError) lastError.value = err
      data.value = null
    } finally {
      loading.value = false
    }
  }

  function bind(id: string | null): void {
    if (sessionId.value === id) return
    sessionId.value = id
    data.value = null
    lastError.value = null
    if (id) void refresh(id)
  }

  const hasSummary = computed(() => data.value?.has_summary === true)
  const hasEntries = computed(() =>
    (data.value?.has_summary === true) || (data.value?.notes.length ?? 0) > 0,
  )
  const compactedCount = computed(() => data.value?.compacted_message_count ?? 0)
  const notes = computed(() => data.value?.notes ?? [])

  async function addNote(
    content: string,
    kind: SessionMemoryNoteKind = 'note',
    id: string | null = sessionId.value,
  ): Promise<void> {
    if (!id) return
    savingNote.value = true
    try {
      await api.addSessionMemoryNote(id, { content, kind })
      await refresh(id)
    } finally {
      savingNote.value = false
    }
  }

  async function deleteNote(
    noteId: number,
    id: string | null = sessionId.value,
  ): Promise<void> {
    if (!id) return
    deletingNoteId.value = noteId
    try {
      await api.deleteSessionMemoryNote(id, noteId)
      await refresh(id)
    } finally {
      deletingNoteId.value = null
    }
  }

  async function clearSummary(id: string | null = sessionId.value): Promise<void> {
    if (!id) return
    clearingSummary.value = true
    try {
      data.value = await api.clearSessionMemorySummary(id)
      lastError.value = null
    } finally {
      clearingSummary.value = false
    }
  }

  return {
    sessionId,
    data,
    loading,
    lastError,
    savingNote,
    clearingSummary,
    deletingNoteId,
    hasSummary,
    hasEntries,
    compactedCount,
    notes,
    bind,
    refresh,
    addNote,
    deleteNote,
    clearSummary,
  }
})

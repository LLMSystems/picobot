import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/lib/api'
import { ApiError } from '@/lib/errors'
import type {
  DisplayMessageSegment,
  DisplayToolCall,
  SubagentLiveEvent,
  SubagentPhase,
  SubagentSummary,
  SubagentTimelineEvent,
} from '@/lib/types'

interface SubagentStreamingState {
  content: string
  toolCalls: DisplayToolCall[]
  segments: DisplayMessageSegment[]
}

const TERMINAL_PHASES: ReadonlySet<SubagentPhase> = new Set([
  'done',
  'failed',
  'cancelled',
])

function isTerminal(phase: SubagentPhase): boolean {
  return TERMINAL_PHASES.has(phase)
}

function parseLive(raw: string): SubagentLiveEvent | null {
  try {
    return JSON.parse(raw) as SubagentLiveEvent
  } catch {
    return null
  }
}

const LIVE_EVENT_NAMES = [
  'subagent_spawned',
  'subagent_phase_changed',
  'subagent_delta',
  'subagent_tool_call_started',
  'subagent_tool_call_finished',
  'subagent_iteration_completed',
  'subagent_completed',
  'subagent_failed',
  'subagent_cancelled',
] as const

const ASSISTANT_EVENT_NAMES = [
  'assistant_started',
  'assistant_delta',
  'assistant_run_started',
  'assistant_tool_call_started',
  'assistant_tool_call_finished',
  'assistant_iteration_completed',
  'assistant_workspace_changed',
  'assistant_done',
  'assistant_error',
] as const

export interface AssistantLiveEvent {
  session_id: string
  run_id: string
  event: string
  data: Record<string, unknown>
  created_at: string
}

function parseAssistantEvent(raw: string): AssistantLiveEvent | null {
  try {
    return JSON.parse(raw) as AssistantLiveEvent
  } catch {
    return null
  }
}

export const useSubagentStore = defineStore('subagents', () => {
  const sessionId = ref<string | null>(null)
  const summaries = ref<Map<string, SubagentSummary>>(new Map())
  const timelines = ref<Map<string, SubagentTimelineEvent[]>>(new Map())
  const streaming = ref<Map<string, SubagentStreamingState>>(new Map())
  const loadedTimelines = ref<Set<string>>(new Set())
  // Ordered list of subagent task_ids currently pinned open in the panel.
  // Wide layout renders these side-by-side; narrow layout shows only the last.
  const openTaskIds = ref<string[]>([])
  const MAX_OPEN_TASKS = 3
  const loadingSummaries = ref(false)
  const loadingTimeline = ref<string | null>(null)
  const lastError = ref<ApiError | null>(null)

  let sseSource: EventSource | null = null
  let onFirstSpawn: ((taskId: string) => void) | null = null
  let onTerminal:
    | ((summary: SubagentSummary) => void)
    | null = null
  let onAssistantEvent:
    | ((ev: AssistantLiveEvent) => void)
    | null = null

  function clear(): void {
    summaries.value = new Map()
    timelines.value = new Map()
    streaming.value = new Map()
    loadedTimelines.value = new Set()
    openTaskIds.value = []
    lastError.value = null
  }

  function ensureStreaming(taskId: string): SubagentStreamingState {
    let s = streaming.value.get(taskId)
    if (!s) {
      s = { content: '', toolCalls: [], segments: [] }
      streaming.value.set(taskId, s)
      streaming.value = new Map(streaming.value)
    }
    return s
  }

  function setSummary(next: SubagentSummary): void {
    const map = new Map(summaries.value)
    map.set(next.task_id, next)
    summaries.value = map
  }

  function updateSummary(
    taskId: string,
    patch: Partial<SubagentSummary>,
  ): void {
    const existing = summaries.value.get(taskId)
    if (!existing) return
    const next: SubagentSummary = { ...existing, ...patch }
    setSummary(next)
  }

  async function loadForSession(sid: string): Promise<void> {
    loadingSummaries.value = true
    lastError.value = null
    try {
      const resp = await api.listSubagents(sid)
      if (sessionId.value !== sid) return
      const map = new Map<string, SubagentSummary>()
      for (const item of resp.items) {
        map.set(item.task_id, item)
        if (!isTerminal(item.phase as SubagentPhase)) {
          ensureStreaming(item.task_id)
        }
      }
      summaries.value = map
    } catch (err) {
      if (err instanceof ApiError) lastError.value = err
    } finally {
      loadingSummaries.value = false
    }
  }

  async function loadTimeline(taskId: string): Promise<void> {
    if (loadedTimelines.value.has(taskId)) return
    const sid = sessionId.value
    if (!sid) return
    loadingTimeline.value = taskId
    try {
      const resp = await api.getSubagentEvents(sid, taskId)
      if (sessionId.value !== sid) return
      const sorted = [...resp.events].sort((a, b) => a.seq - b.seq)
      const tmap = new Map(timelines.value)
      tmap.set(taskId, sorted)
      timelines.value = tmap
      const lset = new Set(loadedTimelines.value)
      lset.add(taskId)
      loadedTimelines.value = lset
    } catch (err) {
      if (err instanceof ApiError) lastError.value = err
    } finally {
      if (loadingTimeline.value === taskId) loadingTimeline.value = null
    }
  }

  function openTask(taskId: string): void {
    const idx = openTaskIds.value.indexOf(taskId)
    if (idx >= 0) {
      // Already open — move to the end so it becomes the "most recently opened"
      // (which is what narrow mode renders).
      openTaskIds.value.splice(idx, 1)
      openTaskIds.value.push(taskId)
    } else {
      // Cap the number of simultaneously open panels — drop the oldest.
      while (openTaskIds.value.length >= MAX_OPEN_TASKS) {
        openTaskIds.value.shift()
      }
      openTaskIds.value.push(taskId)
    }
    const summary = summaries.value.get(taskId)
    if (!summary) return
    if (isTerminal(summary.phase) && !loadedTimelines.value.has(taskId)) {
      void loadTimeline(taskId)
    }
  }

  function closeTask(taskId: string): void {
    const idx = openTaskIds.value.indexOf(taskId)
    if (idx >= 0) openTaskIds.value.splice(idx, 1)
  }

  function closeAllTasks(): void {
    openTaskIds.value = []
  }

  // Back-compat shim: callers that used selectTask(taskId) or selectTask(null)
  // continue to work. null clears all open panels.
  function selectTask(taskId: string | null): void {
    if (taskId === null) {
      closeAllTasks()
    } else {
      openTask(taskId)
    }
  }

  function setOnFirstSpawn(handler: ((taskId: string) => void) | null): void {
    onFirstSpawn = handler
  }

  function setOnTerminal(
    handler: ((summary: SubagentSummary) => void) | null,
  ): void {
    onTerminal = handler
  }

  function setOnAssistantEvent(
    handler: ((ev: AssistantLiveEvent) => void) | null,
  ): void {
    onAssistantEvent = handler
  }

  function notifyTerminal(taskId: string): void {
    const summary = summaries.value.get(taskId)
    if (summary && onTerminal) onTerminal(summary)
  }

  function handleSpawned(ev: SubagentLiveEvent): void {
    const data = ev.data as {
      task_id?: string
      label?: string
      task?: string
      workspace?: string | null
      model?: string | null
    }
    const taskId = data.task_id ?? ev.task_id
    if (!taskId) return
    const exists = summaries.value.has(taskId)
    const summary: SubagentSummary = {
      task_id: taskId,
      parent_session_id: ev.session_id,
      label: data.label ?? ev.label ?? '',
      task: data.task ?? '',
      workspace: data.workspace ?? null,
      phase: 'running',
      started_at: ev.created_at,
      finished_at: null,
      stop_reason: null,
      ok: null,
      error: null,
      usage: {},
      tool_events: [],
      final_content: null,
      model: data.model ?? null,
    }
    setSummary(summary)
    ensureStreaming(taskId)
    if (!exists && onFirstSpawn) onFirstSpawn(taskId)
  }

  function handlePhaseChanged(ev: SubagentLiveEvent): void {
    const data = ev.data as {
      phase?: SubagentPhase
      stop_reason?: string | null
      ok?: boolean | null
    }
    if (!data.phase) return
    const patch: Partial<SubagentSummary> = { phase: data.phase }
    if (data.stop_reason !== undefined) patch.stop_reason = data.stop_reason ?? null
    if (data.ok !== undefined) patch.ok = data.ok ?? null
    if (isTerminal(data.phase) && !summaries.value.get(ev.task_id)?.finished_at) {
      patch.finished_at = ev.created_at
    }
    updateSummary(ev.task_id, patch)
  }

  function handleDelta(ev: SubagentLiveEvent): void {
    const data = ev.data as { delta?: string }
    if (typeof data.delta !== 'string' || !data.delta) return
    const s = ensureStreaming(ev.task_id)
    s.content += data.delta
    const last = s.segments[s.segments.length - 1]
    if (last && last.type === 'text') {
      last.content += data.delta
    } else {
      s.segments.push({ type: 'text', content: data.delta })
    }
  }

  function handleToolStarted(ev: SubagentLiveEvent): void {
    const data = ev.data as {
      id?: string
      name?: string
      arguments?: Record<string, unknown>
    }
    if (!data.id || !data.name) return
    const s = ensureStreaming(ev.task_id)
    const tc: DisplayToolCall = {
      id: data.id,
      name: data.name,
      arguments: data.arguments ?? {},
      status: 'running',
    }
    s.toolCalls.push(tc)
    s.segments.push({ type: 'tool', toolCall: tc })
  }

  function handleToolFinished(ev: SubagentLiveEvent): void {
    const data = ev.data as {
      id?: string
      ok?: boolean
      result?: unknown
    }
    if (!data.id) return
    const s = streaming.value.get(ev.task_id)
    if (!s) return
    const target = s.toolCalls.find((t) => t.id === data.id)
    if (!target) return
    target.ok = data.ok
    target.result = data.result
    target.status = data.ok === false ? 'failed' : 'ok'
  }

  function handleIterationCompleted(ev: SubagentLiveEvent): void {
    const data = ev.data as { usage?: Record<string, number> }
    if (!data.usage) return
    const existing = summaries.value.get(ev.task_id)
    if (!existing) return
    updateSummary(ev.task_id, { usage: { ...existing.usage, ...data.usage } })
  }

  function handleCompleted(ev: SubagentLiveEvent): void {
    const data = ev.data as {
      ok?: boolean
      stop_reason?: string | null
      content?: string | null
      error?: string | null
      usage?: Record<string, number>
    }
    const existing = summaries.value.get(ev.task_id)
    const patch: Partial<SubagentSummary> = {
      phase: 'done',
      finished_at: ev.created_at,
      stop_reason: data.stop_reason ?? null,
      ok: data.ok ?? true,
      error: data.error ?? null,
      final_content: data.content ?? null,
    }
    if (data.usage) {
      patch.usage = { ...(existing?.usage ?? {}), ...data.usage }
    }
    updateSummary(ev.task_id, patch)
    notifyTerminal(ev.task_id)
  }

  function handleFailed(ev: SubagentLiveEvent): void {
    const data = ev.data as {
      ok?: boolean
      stop_reason?: string | null
      content?: string | null
      error?: string | null
    }
    updateSummary(ev.task_id, {
      phase: 'failed',
      finished_at: ev.created_at,
      stop_reason: data.stop_reason ?? 'error',
      ok: data.ok ?? false,
      error: data.error ?? null,
      final_content: data.content ?? null,
    })
    notifyTerminal(ev.task_id)
  }

  function handleCancelled(ev: SubagentLiveEvent): void {
    const data = ev.data as {
      stop_reason?: string | null
      content?: string | null
    }
    updateSummary(ev.task_id, {
      phase: 'cancelled',
      finished_at: ev.created_at,
      stop_reason: data.stop_reason ?? 'cancelled',
      ok: false,
      final_content: data.content ?? null,
    })
    notifyTerminal(ev.task_id)
  }

  function dispatch(ev: SubagentLiveEvent): void {
    switch (ev.event) {
      case 'subagent_spawned':
        handleSpawned(ev)
        break
      case 'subagent_phase_changed':
        handlePhaseChanged(ev)
        break
      case 'subagent_delta':
        handleDelta(ev)
        break
      case 'subagent_tool_call_started':
        handleToolStarted(ev)
        break
      case 'subagent_tool_call_finished':
        handleToolFinished(ev)
        break
      case 'subagent_iteration_completed':
        handleIterationCompleted(ev)
        break
      case 'subagent_completed':
        handleCompleted(ev)
        break
      case 'subagent_failed':
        handleFailed(ev)
        break
      case 'subagent_cancelled':
        handleCancelled(ev)
        break
      default:
        break
    }
  }

  function connectSSE(sid: string): void {
    disconnectSSE()
    sessionId.value = sid
    const url = api.sessionEventStreamUrl(sid)
    const es = new EventSource(url, { withCredentials: false })
    sseSource = es
    for (const name of LIVE_EVENT_NAMES) {
      es.addEventListener(name, (raw) => {
        const me = raw as MessageEvent
        const ev = parseLive(me.data)
        if (!ev) return
        if (sessionId.value !== sid) return
        dispatch(ev)
      })
    }
    for (const name of ASSISTANT_EVENT_NAMES) {
      es.addEventListener(name, (raw) => {
        const me = raw as MessageEvent
        const ev = parseAssistantEvent(me.data)
        if (!ev) return
        if (sessionId.value !== sid) return
        if (onAssistantEvent) onAssistantEvent(ev)
      })
    }
    es.onerror = () => {
      // Browser will auto-reconnect for SSE; nothing to do here.
    }
  }

  function disconnectSSE(): void {
    if (sseSource) {
      sseSource.close()
      sseSource = null
    }
  }

  function bind(sid: string | null): void {
    disconnectSSE()
    clear()
    sessionId.value = sid
    if (!sid) return
    void loadForSession(sid)
    connectSSE(sid)
  }

  const sortedSummaries = computed<SubagentSummary[]>(() => {
    const list = [...summaries.value.values()]
    list.sort((a, b) => b.started_at.localeCompare(a.started_at))
    return list
  })

  const runningCount = computed<number>(() => {
    let n = 0
    for (const s of summaries.value.values()) {
      if (!isTerminal(s.phase)) n += 1
    }
    return n
  })

  const totalCount = computed<number>(() => summaries.value.size)

  // Most-recently-opened summary (used by narrow layout and by callers that
  // still think in single-selection terms).
  const selectedTaskId = computed<string | null>(() =>
    openTaskIds.value.length > 0
      ? (openTaskIds.value[openTaskIds.value.length - 1] ?? null)
      : null,
  )

  const selectedSummary = computed<SubagentSummary | null>(() => {
    const id = selectedTaskId.value
    if (!id) return null
    return summaries.value.get(id) ?? null
  })

  // Ordered SubagentSummary objects for the currently-pinned panels.
  // Wide layout iterates over this to render columns side-by-side.
  const openSummaries = computed<SubagentSummary[]>(() => {
    const out: SubagentSummary[] = []
    for (const id of openTaskIds.value) {
      const s = summaries.value.get(id)
      if (s) out.push(s)
    }
    return out
  })

  function getStreaming(taskId: string): SubagentStreamingState | undefined {
    return streaming.value.get(taskId)
  }

  function getTimeline(taskId: string): SubagentTimelineEvent[] {
    return timelines.value.get(taskId) ?? []
  }

  return {
    sessionId,
    summaries,
    streaming,
    timelines,
    loadedTimelines,
    openTaskIds,
    selectedTaskId,
    loadingSummaries,
    loadingTimeline,
    lastError,
    sortedSummaries,
    runningCount,
    totalCount,
    selectedSummary,
    openSummaries,
    bind,
    clear,
    loadForSession,
    loadTimeline,
    openTask,
    closeTask,
    closeAllTasks,
    selectTask,
    connectSSE,
    disconnectSSE,
    setOnFirstSpawn,
    setOnTerminal,
    setOnAssistantEvent,
    getStreaming,
    getTimeline,
  }
})

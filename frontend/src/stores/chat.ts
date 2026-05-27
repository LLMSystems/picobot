import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/lib/api'
import { ApiError, isAbortError } from '@/lib/errors'
import { runStream } from '@/composables/useChatStream'
import { useSessionsStore } from '@/stores/sessions'
import { useCapabilitiesStore } from '@/stores/capabilities'
import { useSettingsStore } from '@/stores/settings'
import { useSubagentStore } from '@/stores/subagents'
import { useWorkspaceStore } from '@/stores/workspace'
import { useNotifications } from '@/composables/useNotifications'
import type {
  ChatImageInput,
  ChatUsage,
  DisplayMessage,
  DisplayMessageImage,
  DisplayMessageSegment,
  DisplayToolCall,
  SessionMessage,
  SubagentResultPayload,
  WorkspaceChangedData,
} from '@/lib/types'

let localIdSeq = 0
function localId(prefix: string): string {
  localIdSeq += 1
  return `${prefix}-${Date.now()}-${localIdSeq}`
}

function toRelativeWorkspacePath(rawPath: string, sessionId: string): string {
  const marker = `/${sessionId}/`
  const idx = rawPath.indexOf(marker)
  if (idx >= 0) return rawPath.slice(idx + marker.length)
  return rawPath
}

function parseUserContent(
  raw: SessionMessage['content'],
  sessionId: string,
): { text: string; images: DisplayMessageImage[] } {
  if (typeof raw === 'string') return { text: raw, images: [] }
  if (!Array.isArray(raw)) return { text: '', images: [] }
  const texts: string[] = []
  const images: DisplayMessageImage[] = []
  for (const block of raw) {
    if (!block || typeof block !== 'object') continue
    if (block.type === 'text' && typeof block.text === 'string') {
      texts.push(block.text)
    } else if (block.type === 'image') {
      const rawPath = typeof block.path === 'string' ? block.path : null
      const url = typeof block.url === 'string' ? block.url : null
      if (rawPath || url) {
        images.push({
          path: rawPath ? toRelativeWorkspacePath(rawPath, sessionId) : null,
          url,
          detail: block.detail,
        })
      }
    }
  }
  return { text: texts.join('\n'), images }
}

function parseSubagentResultContent(text: string): {
  label: string
  task: string | null
  result: string
} {
  const labelMatch = text.match(/^Subagent\s+\[([^\]]+)\]\s+has finished\./)
  const taskMatch = text.match(/\bTask:\s*\n([\s\S]*?)(?:\n\nOutcome:|\n\nResult:|$)/)
  const resultMatch = text.match(/\bResult:\s*\n([\s\S]*?)(?:\n\nUse this result|$)/)
  return {
    label: labelMatch?.[1]?.trim() ?? '',
    task: taskMatch?.[1]?.trim() || null,
    result: resultMatch?.[1]?.trim() ?? text,
  }
}

function buildSubagentResultMessage(
  m: SessionMessage,
): DisplayMessage | null {
  const meta = m.metadata
  if (!meta || meta.kind !== 'subagent_result') return null
  const raw = typeof m.content === 'string' ? m.content : ''
  const parsed = parseSubagentResultContent(raw)
  const taskId = typeof meta.task_id === 'string' ? meta.task_id : ''
  if (!taskId) return null
  const workspace =
    typeof meta.workspace === 'string' ? meta.workspace : null
  const payload: SubagentResultPayload = {
    taskId,
    label: parsed.label || taskId,
    task: parsed.task,
    ok: meta.ok !== false,
    stopReason:
      typeof meta.stop_reason === 'string' ? meta.stop_reason : null,
    result: parsed.result,
    workspace,
  }
  return {
    id: m.id,
    role: 'subagent_result',
    content: parsed.result,
    created_at: m.created_at,
    toolCalls: [],
    segments: [],
    status: 'complete',
    subagent: payload,
  }
}

function hydrateHistory(
  messages: SessionMessage[],
  sessionId: string,
): DisplayMessage[] {
  const out: DisplayMessage[] = []
  const toolResultById = new Map<string, SessionMessage>()
  for (const m of messages) {
    if (m.role === 'tool' && m.tool_call_id) {
      toolResultById.set(m.tool_call_id, m)
    }
  }
  for (const m of messages) {
    if (m.role === 'system') {
      const sub = buildSubagentResultMessage(m)
      if (sub) out.push(sub)
      continue
    }
    if (m.role === 'user') {
      const parsed = parseUserContent(m.content, sessionId)
      const fallbackImages: DisplayMessageImage[] | undefined = m.images?.length
        ? m.images.map((img) => ({
            path: img.path ? toRelativeWorkspacePath(img.path, sessionId) : null,
            url: img.url ?? null,
            detail: img.detail,
          }))
        : undefined
      const images =
        parsed.images.length > 0 ? parsed.images : fallbackImages
      out.push({
        id: m.id,
        role: 'user',
        content: parsed.text,
        created_at: m.created_at,
        toolCalls: [],
        segments: [],
        status: 'complete',
        images,
      })
    } else if (m.role === 'assistant') {
      const toolCalls: DisplayToolCall[] = []
      const segments: DisplayMessageSegment[] = []
      const assistantText =
        typeof m.content === 'string' ? m.content : ''
      if (assistantText) {
        segments.push({ type: 'text', content: assistantText })
      }
      if (m.tool_calls) {
        for (const tc of m.tool_calls) {
          const result = toolResultById.get(tc.id)
          let args: Record<string, unknown> = {}
          if (tc.function?.arguments) {
            try {
              args = JSON.parse(tc.function.arguments) as Record<string, unknown>
            } catch {
              args = { raw: tc.function.arguments }
            }
          }
          const toolCall: DisplayToolCall = {
            id: tc.id,
            name: tc.function?.name ?? 'tool',
            arguments: args,
            result: result?.content,
            ok: true,
            status: 'ok',
          }
          toolCalls.push(toolCall)
          segments.push({ type: 'tool', toolCall })
        }
      }
      if (assistantText || toolCalls.length > 0) {
        out.push({
          id: m.id,
          role: 'assistant',
          content: assistantText,
          created_at: m.created_at,
          toolCalls,
          segments,
          status: 'complete',
        })
      }
    }
  }
  return out
}

export const useChatStore = defineStore('chat', () => {
  const currentSessionId = ref<string | null>(null)
  const messages = ref<DisplayMessage[]>([])
  const streamingMessage = ref<DisplayMessage | null>(null)
  const autoResumeMessage = ref<DisplayMessage | null>(null)
  const autoResumeRunId = ref<string | null>(null)
  const autoResuming = ref(false)
  // Cards that arrived while a stream was in progress; they need to render
  // after the streaming bubble, and get flushed into `messages` on commit.
  const deferredMessages = ref<DisplayMessage[]>([])
  const runStatus = ref<'idle' | 'streaming' | 'error'>('idle')
  const lastError = ref<ApiError | null>(null)
  const loadingHistory = ref(false)
  let abortController: AbortController | null = null

  let wsPendingPaths = new Set<string>()
  let wsPendingFullInvalidate = false
  let wsDebounceTimer: number | null = null

  function flushWorkspaceUpdates() {
    wsDebounceTimer = null
    const ws = useWorkspaceStore()
    if (ws.sessionId !== currentSessionId.value) {
      wsPendingPaths = new Set()
      wsPendingFullInvalidate = false
      return
    }
    if (wsPendingFullInvalidate) {
      wsPendingFullInvalidate = false
      wsPendingPaths = new Set()
      void ws.refreshExpanded()
      return
    }
    const paths = [...wsPendingPaths]
    wsPendingPaths = new Set()
    if (paths.length) void ws.refreshPaths(paths)
  }

  function scheduleWorkspaceUpdate(d: WorkspaceChangedData) {
    if (d.paths.length === 0) {
      wsPendingFullInvalidate = true
    } else {
      for (const p of d.paths) wsPendingPaths.add(p)
    }
    if (wsDebounceTimer !== null) window.clearTimeout(wsDebounceTimer)
    wsDebounceTimer = window.setTimeout(flushWorkspaceUpdates, 250)
  }

  function ensureAutoResumeMessage(runId: string): DisplayMessage {
    if (autoResumeMessage.value && autoResumeRunId.value === runId) {
      return autoResumeMessage.value
    }
    // New run — commit any previous in-flight message defensively.
    if (autoResumeMessage.value) {
      autoResumeMessage.value.status = 'aborted'
      messages.value.push(autoResumeMessage.value)
    }
    const msg: DisplayMessage = {
      id: `auto-${runId}`,
      role: 'assistant',
      content: '',
      created_at: new Date().toISOString(),
      toolCalls: [],
      segments: [],
      status: 'streaming',
    }
    autoResumeMessage.value = msg
    autoResumeRunId.value = runId
    autoResuming.value = true
    return msg
  }

  function commitAutoResumeMessage(): void {
    const msg = autoResumeMessage.value
    if (!msg) {
      autoResumeRunId.value = null
      autoResuming.value = false
      return
    }
    if (!msg.content && msg.toolCalls.length === 0) {
      // Nothing to show; drop.
    } else {
      messages.value.push(msg)
    }
    autoResumeMessage.value = null
    autoResumeRunId.value = null
    autoResuming.value = false
    flushDeferred()
  }

  function handleAssistantEvent(
    ev: import('@/stores/subagents').AssistantLiveEvent,
  ): void {
    const runId = ev.run_id
    if (!runId) return
    switch (ev.event) {
      case 'assistant_started': {
        ensureAutoResumeMessage(runId)
        break
      }
      case 'assistant_delta': {
        const msg = ensureAutoResumeMessage(runId)
        const delta = (ev.data as { delta?: string }).delta
        if (typeof delta !== 'string' || !delta) break
        msg.content += delta
        const last = msg.segments[msg.segments.length - 1]
        if (last && last.type === 'text') {
          last.content += delta
        } else {
          msg.segments.push({ type: 'text', content: delta })
        }
        break
      }
      case 'assistant_tool_call_started': {
        const msg = ensureAutoResumeMessage(runId)
        const d = ev.data as {
          id?: string
          name?: string
          arguments?: Record<string, unknown>
        }
        if (!d.id || !d.name) break
        const tc: DisplayToolCall = {
          id: d.id,
          name: d.name,
          arguments: d.arguments ?? {},
          status: 'running',
        }
        msg.toolCalls.push(tc)
        msg.segments.push({ type: 'tool', toolCall: tc })
        break
      }
      case 'assistant_tool_call_finished': {
        const msg = autoResumeMessage.value
        if (!msg || autoResumeRunId.value !== runId) break
        const d = ev.data as {
          id?: string
          ok?: boolean
          result?: unknown
        }
        const target = msg.toolCalls.find((t) => t.id === d.id)
        if (!target) break
        target.ok = d.ok
        target.result = d.result
        target.status = d.ok === false ? 'failed' : 'ok'
        break
      }
      case 'assistant_workspace_changed': {
        scheduleWorkspaceUpdate(ev.data as unknown as WorkspaceChangedData)
        break
      }
      case 'assistant_done': {
        const msg = ensureAutoResumeMessage(runId)
        const d = ev.data as {
          content?: string
          usage?: ChatUsage
          tools_used?: string[]
        }
        msg.status = 'complete'
        msg.usage = d.usage
        msg.toolsUsed = d.tools_used
        if (d.content && !msg.content) {
          msg.content = d.content
          if (msg.segments.length === 0) {
            msg.segments.push({ type: 'text', content: d.content })
          }
        }
        commitAutoResumeMessage()
        break
      }
      case 'assistant_error': {
        const msg = autoResumeMessage.value
        if (msg && autoResumeRunId.value === runId) {
          msg.status = 'error'
          messages.value.push(msg)
        }
        autoResumeMessage.value = null
        autoResumeRunId.value = null
        autoResuming.value = false
        flushDeferred()
        break
      }
      default:
        break
    }
  }

  function insertSubagentResultMessage(
    summary: import('@/lib/types').SubagentSummary,
  ): void {
    const taskId = summary.task_id
    if (!taskId) return
    if (messages.value.some((m) => m.subagent?.taskId === taskId)) return
    if (deferredMessages.value.some((m) => m.subagent?.taskId === taskId)) return
    const payload: SubagentResultPayload = {
      taskId,
      label: summary.label || taskId,
      task: summary.task || null,
      ok: summary.ok !== false,
      stopReason: summary.stop_reason ?? null,
      result: summary.final_content ?? '',
      workspace: summary.workspace ?? null,
    }
    const card: DisplayMessage = {
      id: `subagent-result-${taskId}`,
      role: 'subagent_result',
      content: payload.result,
      created_at: summary.finished_at ?? new Date().toISOString(),
      toolCalls: [],
      segments: [],
      status: 'complete',
      subagent: payload,
    }
    // If something is currently streaming, the dispatch that produced this
    // subagent is still inside that bubble — render the card AFTER, not
    // before, by holding it in the deferred buffer until commit.
    if (streamingMessage.value || autoResumeMessage.value) {
      deferredMessages.value.push(card)
    } else {
      messages.value.push(card)
    }
  }

  function flushDeferred(): void {
    if (deferredMessages.value.length === 0) return
    messages.value.push(...deferredMessages.value)
    deferredMessages.value = []
  }

  function isAgentBrowserCommand(name: string, args: Record<string, unknown>): boolean {
    if (name !== 'exec' && name !== 'shell') return false
    const cmd = args?.command
    if (typeof cmd !== 'string') return false
    return /(^|[\s/])agent-browser(\s|$)/.test(cmd.trim())
  }

  function maybeFocusBrowserForTool(name: string, args: Record<string, unknown>) {
    if (!isAgentBrowserCommand(name, args)) return
    const caps = useCapabilitiesStore()
    if (!caps.data.features.session_workspace) return
    const ws = useWorkspaceStore()
    ws.focusBrowser()
  }

  function abortIfStreaming(reason: 'switch' | 'manual' = 'manual') {
    if (runStatus.value !== 'streaming') return
    abortController?.abort()
    if (streamingMessage.value) {
      if (reason === 'manual') {
        streamingMessage.value.status = 'aborted'
        messages.value.push(streamingMessage.value)
      }
      streamingMessage.value = null
    }
    // On manual stop, deferred cards still belong after the (aborted) bubble.
    // On switch, switchTo() clears everything below anyway.
    if (reason === 'manual') flushDeferred()
    runStatus.value = 'idle'
    abortController = null
  }

  async function switchTo(id: string | null) {
    abortIfStreaming('switch')
    currentSessionId.value = id
    messages.value = []
    streamingMessage.value = null
    runStatus.value = 'idle'
    lastError.value = null
    const subagents = useSubagentStore()
    subagents.setOnFirstSpawn(null)
    subagents.setOnTerminal(null)
    subagents.setOnAssistantEvent(null)
    autoResumeMessage.value = null
    autoResumeRunId.value = null
    autoResuming.value = false
    deferredMessages.value = []
    subagents.bind(id)
    if (id) {
      const ws = useWorkspaceStore()
      subagents.setOnFirstSpawn(() => {
        ws.focusAgents()
      })
      subagents.setOnTerminal((summary) => {
        insertSubagentResultMessage(summary)
      })
      subagents.setOnAssistantEvent((ev) => {
        handleAssistantEvent(ev)
      })
    }
    if (!id) return
    loadingHistory.value = true
    try {
      const { messages: history } = await api.getMessages(id)
      if (currentSessionId.value === id) {
        const hydrated = hydrateHistory(history, id)
        if (hydrated.length > 0) {
          messages.value = hydrated
        }
      }
    } catch (e) {
      if (e instanceof ApiError) lastError.value = e
    } finally {
      loadingHistory.value = false
    }
  }

  function rewriteMentions(input: string): string {
    return input.replace(
      /(^|\s)@([^\s@]+)/g,
      (_match, prefix: string, path: string) =>
        `${prefix}「workspace 檔案：${path}」`,
    )
  }

  async function send(
    text: string,
    images: ChatImageInput[] = [],
    model: string | null = null,
  ): Promise<void> {
    const sessionId = currentSessionId.value
    if (!sessionId) return
    if (runStatus.value === 'streaming') return
    if (autoResuming.value) return
    const trimmed = text.trim()
    if (!trimmed && images.length === 0) return

    text = rewriteMentions(text)

    const caps = useCapabilitiesStore()
    const settings = useSettingsStore()
    const sessions = useSessionsStore()

    runStatus.value = 'streaming'
    lastError.value = null
    abortController = new AbortController()

    const displayImages: DisplayMessageImage[] | undefined = images.length
      ? images.map((img) => ({
          path: img.path ?? null,
          url: img.url ?? null,
          detail: img.detail,
        }))
      : undefined

    const userMsg: DisplayMessage = {
      id: localId('user'),
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
      toolCalls: [],
      segments: [],
      status: 'complete',
      images: displayImages,
    }
    messages.value.push(userMsg)

    const assistantMsg: DisplayMessage = {
      id: localId('assistant'),
      role: 'assistant',
      content: '',
      created_at: new Date().toISOString(),
      toolCalls: [],
      segments: [],
      status: 'streaming',
    }
    streamingMessage.value = assistantMsg

    try {
      if (caps.streamingEnabled) {
        await runStream(
          {
            session_id: sessionId,
            message: text,
            ...(images.length ? { images } : {}),
            ...(model ? { model } : {}),
            ...settings.chatOverrides,
          },
          abortController.signal,
          {
            onToolStart: (tc) => {
              const sm = streamingMessage.value
              if (!sm) return
              sm.toolCalls.push(tc)
              sm.segments.push({ type: 'tool', toolCall: tc })
              maybeFocusBrowserForTool(tc.name, tc.arguments)
            },
            onToolFinish: (tc) => {
              const target = streamingMessage.value?.toolCalls.find(
                (t) => t.id === tc.id,
              )
              if (target) {
                target.result = tc.result
                target.ok = tc.ok
                target.status = tc.status
              }
            },
            onDelta: (t) => {
              const sm = streamingMessage.value
              if (!sm) return
              sm.content += t
              const last = sm.segments[sm.segments.length - 1]
              if (last && last.type === 'text') {
                last.content += t
              } else {
                sm.segments.push({ type: 'text', content: t })
              }
            },
            onDone: (done) => {
              if (!streamingMessage.value) return
              streamingMessage.value.status = 'complete'
              streamingMessage.value.usage = done.usage
              streamingMessage.value.toolsUsed = done.tools_used
              if (done.content && !streamingMessage.value.content) {
                streamingMessage.value.content = done.content
                if (streamingMessage.value.segments.length === 0) {
                  streamingMessage.value.segments.push({
                    type: 'text',
                    content: done.content,
                  })
                }
              }
              const finalContent = streamingMessage.value.content
              messages.value.push(streamingMessage.value)
              streamingMessage.value = null
              flushDeferred()
              const notifs = useNotifications()
              notifs.notify(
                'Picobot 完成回應',
                finalContent.slice(0, 140) || undefined,
              )
            },
            onWorkspaceChanged: (d) => scheduleWorkspaceUpdate(d),
          },
        )
      } else {
        const resp = await api.chat({
          session_id: sessionId,
          message: text,
          ...(images.length ? { images } : {}),
          ...(model ? { model } : {}),
          ...settings.chatOverrides,
        })
        assistantMsg.content = resp.content
        if (resp.content) {
          assistantMsg.segments.push({ type: 'text', content: resp.content })
        }
        assistantMsg.status = 'complete'
        assistantMsg.usage = resp.usage
        assistantMsg.toolsUsed = resp.tools_used
        messages.value.push(assistantMsg)
        streamingMessage.value = null
        flushDeferred()
        for (const ev of resp.events) {
          if (ev.event === 'workspace_changed') {
            scheduleWorkspaceUpdate(ev.data as WorkspaceChangedData)
          } else if (ev.event === 'tool_call_started') {
            const d = ev.data as { name: string; arguments?: Record<string, unknown> }
            maybeFocusBrowserForTool(d.name, d.arguments ?? {})
          }
        }
      }

      sessions.touchAfterSend(sessionId, {
        user: text,
        assistant: (assistantMsg.content || '').slice(0, 100),
      })
    } catch (err) {
      if (isAbortError(err)) {
        if (streamingMessage.value) {
          streamingMessage.value.status = 'aborted'
          messages.value.push(streamingMessage.value)
          streamingMessage.value = null
        }
        flushDeferred()
      } else {
        if (err instanceof ApiError) lastError.value = err
        runStatus.value = 'error'
        if (streamingMessage.value) {
          streamingMessage.value.status = 'error'
          messages.value.push(streamingMessage.value)
          streamingMessage.value = null
        }
        flushDeferred()
        throw err
      }
    } finally {
      if (runStatus.value !== 'error') runStatus.value = 'idle'
      abortController = null
    }
  }

  function stop() {
    abortIfStreaming('manual')
  }

  function retryLastUser(): string | null {
    for (let i = messages.value.length - 1; i >= 0; i--) {
      const m = messages.value[i]
      if (m && m.role === 'user') return m.content
    }
    return null
  }

  function findPrecedingUser(
    assistantMessageId: string,
  ): DisplayMessage | null {
    const idx = messages.value.findIndex((m) => m.id === assistantMessageId)
    if (idx < 0) return null
    for (let i = idx - 1; i >= 0; i--) {
      const m = messages.value[i]
      if (m && m.role === 'user') return m
    }
    return null
  }

  function isLastAssistant(messageId: string): boolean {
    for (let i = messages.value.length - 1; i >= 0; i--) {
      const m = messages.value[i]
      if (!m) continue
      if (m.role === 'assistant') return m.id === messageId
      if (m.role === 'user') return false
    }
    return false
  }

  async function regenerate(
    assistantMessageId: string,
    model: string | null = null,
  ): Promise<void> {
    if (runStatus.value === 'streaming') return
    const user = findPrecedingUser(assistantMessageId)
    if (!user) return
    const images: ChatImageInput[] = (user.images ?? [])
      .filter((img) => img.path || img.url)
      .map((img) => ({
        ...(img.path ? { path: img.path } : {}),
        ...(img.url ? { url: img.url } : {}),
        ...(img.detail ? { detail: img.detail } : {}),
      }))
    await send(user.content, images, model)
  }

  async function editAndResend(
    userMessageId: string,
    newText: string,
    model: string | null = null,
  ): Promise<void> {
    if (runStatus.value === 'streaming') return
    const target = messages.value.find((m) => m.id === userMessageId)
    if (!target || target.role !== 'user') return
    const images: ChatImageInput[] = (target.images ?? [])
      .filter((img) => img.path || img.url)
      .map((img) => ({
        ...(img.path ? { path: img.path } : {}),
        ...(img.url ? { url: img.url } : {}),
        ...(img.detail ? { detail: img.detail } : {}),
      }))
    await send(newText, images, model)
  }

  const isStreaming = computed(
    () => runStatus.value === 'streaming' || autoResuming.value,
  )

  return {
    currentSessionId,
    messages,
    streamingMessage,
    autoResumeMessage,
    autoResuming,
    deferredMessages,
    runStatus,
    isStreaming,
    lastError,
    loadingHistory,
    switchTo,
    send,
    stop,
    retryLastUser,
    regenerate,
    editAndResend,
    isLastAssistant,
  }
})

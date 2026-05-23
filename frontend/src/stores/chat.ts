import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/lib/api'
import { ApiError, isAbortError } from '@/lib/errors'
import { runStream } from '@/composables/useChatStream'
import { useSessionsStore } from '@/stores/sessions'
import { useCapabilitiesStore } from '@/stores/capabilities'
import { useWorkspaceStore } from '@/stores/workspace'
import type {
  ChatImageInput,
  DisplayMessage,
  DisplayMessageImage,
  DisplayMessageSegment,
  DisplayToolCall,
  SessionMessage,
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

  async function send(
    text: string,
    images: ChatImageInput[] = [],
    model: string | null = null,
  ): Promise<void> {
    const sessionId = currentSessionId.value
    if (!sessionId) return
    if (runStatus.value === 'streaming') return
    const trimmed = text.trim()
    if (!trimmed && images.length === 0) return

    const caps = useCapabilitiesStore()
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
              messages.value.push(streamingMessage.value)
              streamingMessage.value = null
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
      } else {
        if (err instanceof ApiError) lastError.value = err
        runStatus.value = 'error'
        if (streamingMessage.value) {
          streamingMessage.value.status = 'error'
          messages.value.push(streamingMessage.value)
          streamingMessage.value = null
        }
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

  const isStreaming = computed(() => runStatus.value === 'streaming')

  return {
    currentSessionId,
    messages,
    streamingMessage,
    runStatus,
    isStreaming,
    lastError,
    loadingHistory,
    switchTo,
    send,
    stop,
    retryLastUser,
  }
})

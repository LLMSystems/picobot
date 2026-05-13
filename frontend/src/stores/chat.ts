import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/lib/api'
import { ApiError, isAbortError } from '@/lib/errors'
import { runStream } from '@/composables/useChatStream'
import { useSessionsStore } from '@/stores/sessions'
import { useCapabilitiesStore } from '@/stores/capabilities'
import type {
  DisplayMessage,
  DisplayToolCall,
  SessionMessage,
} from '@/lib/types'

let localIdSeq = 0
function localId(prefix: string): string {
  localIdSeq += 1
  return `${prefix}-${Date.now()}-${localIdSeq}`
}

function hydrateHistory(messages: SessionMessage[]): DisplayMessage[] {
  const out: DisplayMessage[] = []
  const toolResultById = new Map<string, SessionMessage>()
  for (const m of messages) {
    if (m.role === 'tool' && m.tool_call_id) {
      toolResultById.set(m.tool_call_id, m)
    }
  }
  for (const m of messages) {
    if (m.role === 'user') {
      out.push({
        id: m.id,
        role: 'user',
        content: m.content,
        created_at: m.created_at,
        toolCalls: [],
        status: 'complete',
      })
    } else if (m.role === 'assistant') {
      const toolCalls: DisplayToolCall[] = []
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
          toolCalls.push({
            id: tc.id,
            name: tc.function?.name ?? 'tool',
            arguments: args,
            result: result?.content,
            ok: true,
            status: 'ok',
          })
        }
      }
      if (m.content || toolCalls.length > 0) {
        out.push({
          id: m.id,
          role: 'assistant',
          content: m.content ?? '',
          created_at: m.created_at,
          toolCalls,
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
        messages.value = hydrateHistory(history)
      }
    } catch (e) {
      if (e instanceof ApiError) lastError.value = e
    } finally {
      loadingHistory.value = false
    }
  }

  async function send(text: string): Promise<void> {
    const sessionId = currentSessionId.value
    if (!sessionId) return
    if (runStatus.value === 'streaming') return
    const trimmed = text.trim()
    if (!trimmed) return

    const caps = useCapabilitiesStore()
    const sessions = useSessionsStore()

    runStatus.value = 'streaming'
    lastError.value = null
    abortController = new AbortController()

    const userMsg: DisplayMessage = {
      id: localId('user'),
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
      toolCalls: [],
      status: 'complete',
    }
    messages.value.push(userMsg)

    const assistantMsg: DisplayMessage = {
      id: localId('assistant'),
      role: 'assistant',
      content: '',
      created_at: new Date().toISOString(),
      toolCalls: [],
      status: 'streaming',
    }
    streamingMessage.value = assistantMsg

    try {
      if (caps.streamingEnabled) {
        await runStream(
          { session_id: sessionId, message: text },
          abortController.signal,
          {
            onToolStart: (tc) => {
              streamingMessage.value?.toolCalls.push(tc)
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
              if (streamingMessage.value) {
                streamingMessage.value.content += t
              }
            },
            onDone: (done) => {
              if (!streamingMessage.value) return
              streamingMessage.value.status = 'complete'
              streamingMessage.value.usage = done.usage
              streamingMessage.value.toolsUsed = done.tools_used
              if (done.content && !streamingMessage.value.content) {
                streamingMessage.value.content = done.content
              }
              messages.value.push(streamingMessage.value)
              streamingMessage.value = null
            },
          },
        )
      } else {
        const resp = await api.chat({ session_id: sessionId, message: text })
        assistantMsg.content = resp.content
        assistantMsg.status = 'complete'
        assistantMsg.usage = resp.usage
        assistantMsg.toolsUsed = resp.tools_used
        messages.value.push(assistantMsg)
        streamingMessage.value = null
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

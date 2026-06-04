import { parseSse } from '@/lib/sse'
import { ApiError } from '@/lib/errors'
import { API_BASE } from '@/lib/api'
import type {
  ApiErrorBody,
  ChatRuntimeEvent,
  ChatImageInput,
  ChatOverrides,
  DoneData,
  StreamErrorData,
} from '@/lib/types'

export interface StreamHandlers {
  onRuntimeEvent?: (event: ChatRuntimeEvent) => void
  onDelta: (text: string) => void
  onDone: (data: DoneData) => void
}

export async function runStream(
  body: {
    session_id: string
    message: string
    client_request_id?: string
    images?: ChatImageInput[]
    model?: string
  } & ChatOverrides,
  signal: AbortSignal,
  h: StreamHandlers,
): Promise<void> {
  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(body),
    signal,
  })

  const requestId = res.headers.get('X-Request-Id') ?? undefined

  if (!res.ok || !res.body) {
    let errBody: ApiErrorBody | undefined
    try {
      errBody = (await res.json()) as ApiErrorBody
    } catch {
      // ignore
    }
    throw new ApiError(
      errBody?.error?.code ?? 'STREAM_FAILED',
      errBody?.error?.message ?? `HTTP ${res.status}`,
      errBody?.error?.request_id ?? requestId,
      res.status,
    )
  }

  type PendingBatch =
    | { kind: 'delta'; text: string }
    | { kind: 'reasoning_delta'; data: ChatRuntimeEvent['data']; text: string }

  const pending: PendingBatch[] = []
  let flushHandle: number | null = null

  const scheduleFrame = (callback: FrameRequestCallback): number => {
    if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
      return window.requestAnimationFrame(callback)
    }
    return window.setTimeout(() => callback(performance.now()), 16)
  }
  const cancelFrame = (handle: number): void => {
    if (typeof window !== 'undefined' && typeof window.cancelAnimationFrame === 'function') {
      window.cancelAnimationFrame(handle)
    } else {
      window.clearTimeout(handle)
    }
  }
  const scheduleFlush = (): void => {
    if (flushHandle !== null) return
    flushHandle = scheduleFrame(() => {
      flushHandle = null
      flushPending()
    })
  }
  const pushDelta = (text: string): void => {
    if (!text) return
    const last = pending[pending.length - 1]
    if (last?.kind === 'delta') {
      last.text += text
    } else {
      pending.push({ kind: 'delta', text })
    }
    scheduleFlush()
  }
  const pushReasoningDelta = (data: ChatRuntimeEvent['data']): void => {
    if (!data || typeof data !== 'object') return
    const delta = (data as { delta?: unknown }).delta
    if (typeof delta !== 'string' || !delta) return
    const last = pending[pending.length - 1]
    if (last?.kind === 'reasoning_delta') {
      last.text += delta
      last.data = { ...(last.data as Record<string, unknown>), ...data, delta: last.text }
    } else {
      pending.push({ kind: 'reasoning_delta', data, text: delta })
    }
    scheduleFlush()
  }
  function flushPending(): void {
    if (flushHandle !== null) {
      cancelFrame(flushHandle)
      flushHandle = null
    }
    while (pending.length > 0) {
      const item = pending.shift()
      if (!item) continue
      if (item.kind === 'delta') {
        h.onDelta(item.text)
      } else {
        h.onRuntimeEvent?.({
          event: 'reasoning_delta',
          data: { ...(item.data as Record<string, unknown>), delta: item.text },
        })
      }
    }
  }

  try {
    for await (const evt of parseSse(res.body, signal)) {
      switch (evt.event) {
        case 'run_started':
        case 'tool_call_started':
        case 'tool_call_finished':
        case 'image_injected':
        case 'workspace_changed':
        case 'memory_compaction_started':
        case 'memory_compaction_finished':
        case 'memory_compaction_skipped':
        case 'memory_compaction_failed': {
          flushPending()
          const data = JSON.parse(evt.data) as ChatRuntimeEvent['data']
          h.onRuntimeEvent?.({
            event: evt.event,
            data,
          })
          break
        }
        case 'reasoning_delta': {
          const data = JSON.parse(evt.data) as ChatRuntimeEvent['data']
          pushReasoningDelta(data)
          break
        }
        case 'delta':
          pushDelta(evt.data)
          break
        case 'done': {
          flushPending()
          const d = JSON.parse(evt.data) as DoneData
          h.onDone(d)
          return
        }
        case 'error': {
          flushPending()
          const d = JSON.parse(evt.data) as StreamErrorData
          throw new ApiError(d.code, d.message, d.request_id)
        }
      }
    }
    flushPending()
  } finally {
    if (flushHandle !== null) {
      cancelFrame(flushHandle)
      flushHandle = null
    }
  }
}

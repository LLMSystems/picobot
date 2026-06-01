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

  for await (const evt of parseSse(res.body, signal)) {
    switch (evt.event) {
      case 'run_started':
      case 'reasoning_delta':
      case 'tool_call_started':
      case 'tool_call_finished':
      case 'workspace_changed':
      case 'memory_compaction_started':
      case 'memory_compaction_finished':
      case 'memory_compaction_skipped':
      case 'memory_compaction_failed': {
        const data = JSON.parse(evt.data) as ChatRuntimeEvent['data']
        h.onRuntimeEvent?.({
          event: evt.event,
          data,
        })
        break
      }
      case 'delta':
        h.onDelta(evt.data)
        break
      case 'done': {
        const d = JSON.parse(evt.data) as DoneData
        h.onDone(d)
        return
      }
      case 'error': {
        const d = JSON.parse(evt.data) as StreamErrorData
        throw new ApiError(d.code, d.message, d.request_id)
      }
    }
  }
}

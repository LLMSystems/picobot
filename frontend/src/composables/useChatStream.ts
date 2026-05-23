import { parseSse } from '@/lib/sse'
import { ApiError } from '@/lib/errors'
import { API_BASE } from '@/lib/api'
import type {
  ApiErrorBody,
  ChatImageInput,
  DisplayToolCall,
  DoneData,
  StreamErrorData,
  ToolCallFinishedData,
  ToolCallStartedData,
  WorkspaceChangedData,
} from '@/lib/types'

export interface StreamHandlers {
  onRunStarted?: () => void
  onToolStart: (tc: DisplayToolCall) => void
  onToolFinish: (tc: { id: string; result: unknown; ok: boolean; status: 'ok' | 'failed' }) => void
  onDelta: (text: string) => void
  onDone: (data: DoneData) => void
  onWorkspaceChanged?: (data: WorkspaceChangedData) => void
}

export async function runStream(
  body: {
    session_id: string
    message: string
    client_request_id?: string
    images?: ChatImageInput[]
  },
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
        h.onRunStarted?.()
        break
      case 'tool_call_started': {
        const d = JSON.parse(evt.data) as ToolCallStartedData
        h.onToolStart({
          id: d.id,
          name: d.name,
          arguments: d.arguments ?? {},
          status: 'running',
        })
        break
      }
      case 'tool_call_finished': {
        const d = JSON.parse(evt.data) as ToolCallFinishedData
        h.onToolFinish({
          id: d.id,
          result: d.result,
          ok: d.ok,
          status: d.ok ? 'ok' : 'failed',
        })
        break
      }
      case 'workspace_changed': {
        const d = JSON.parse(evt.data) as WorkspaceChangedData
        h.onWorkspaceChanged?.(d)
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

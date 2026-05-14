import type {
  Capabilities,
  SessionMessage,
  SessionSummary,
  ApiErrorBody,
  ChatResponse,
  WorkspaceFileResponse,
  WorkspaceTreeResponse,
} from './types'
import { ApiError } from './errors'

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined) continue
    sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

export const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })
  const requestId = res.headers.get('X-Request-Id') ?? undefined
  if (!res.ok) {
    let body: ApiErrorBody | undefined
    try {
      body = (await res.json()) as ApiErrorBody
    } catch {
      // ignore parse failure
    }
    throw new ApiError(
      body?.error?.code ?? 'UNKNOWN',
      body?.error?.message ?? res.statusText ?? 'Request failed',
      body?.error?.request_id ?? requestId,
      res.status,
    )
  }
  return (await res.json()) as T
}

export const api = {
  health: () => request<{ status: string }>('/health'),

  capabilities: () => request<Capabilities>('/capabilities'),

  listSessions: () => request<{ sessions: SessionSummary[] }>('/sessions'),

  createSession: (body: { title?: string; session_id?: string } = {}) =>
    request<SessionSummary>('/sessions', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  renameSession: (id: string, title: string) =>
    request<SessionSummary>(`/sessions/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify({ title }),
    }),

  deleteSession: (id: string) =>
    request<{ session_id: string; deleted: boolean }>(
      `/sessions/${encodeURIComponent(id)}`,
      { method: 'DELETE' },
    ),

  getMessages: (id: string) =>
    request<{ session_id: string; messages: SessionMessage[] }>(
      `/sessions/${encodeURIComponent(id)}/messages`,
    ),

  chat: (body: { session_id: string; message: string }) =>
    request<ChatResponse>('/chat', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  listWorkspaceTree: (
    id: string,
    params: { path?: string; recursive?: boolean; max_entries?: number } = {},
  ) =>
    request<WorkspaceTreeResponse>(
      `/sessions/${encodeURIComponent(id)}/workspace/tree${qs(params)}`,
    ),

  readWorkspaceFile: (
    id: string,
    params: { path: string; offset?: number; limit?: number },
  ) =>
    request<WorkspaceFileResponse>(
      `/sessions/${encodeURIComponent(id)}/workspace/file${qs(params)}`,
    ),
}

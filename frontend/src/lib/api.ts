import type {
  Capabilities,
  ChatImageInput,
  SessionMessage,
  SessionSummary,
  ApiErrorBody,
  ChatResponse,
  WorkspaceFileResponse,
  WorkspaceTreeResponse,
  WorkspaceUploadResponse,
  WorkspaceDeleteResponse,
  WorkspaceMkdirResponse,
  WorkspaceMoveResponse,
  WorkspaceCreateFileResponse,
  WorkspaceDeleteDirectoryResponse,
  WorkspaceSaveFileResponse,
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
  return parseResponse<T>(res)
}

async function requestRaw<T>(path: string, init: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init)
  return parseResponse<T>(res)
}

async function parseResponse<T>(res: Response): Promise<T> {
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

  chromeHealth: () =>
    request<{ chrome_alive: boolean; cdp_port: number }>('/health/chrome'),

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

  chat: (body: {
    session_id: string
    message: string
    images?: ChatImageInput[]
    model?: string
  }) =>
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

  workspaceFileRawUrl: (id: string, path: string): string =>
    `${API_BASE}/sessions/${encodeURIComponent(id)}/workspace/file/raw${qs({ path })}`,

  uploadWorkspaceFiles: (
    id: string,
    params: { path?: string; overwrite?: boolean },
    files: File[],
  ) => {
    const formData = new FormData()
    for (const f of files) formData.append('files', f, f.name)
    return requestRaw<WorkspaceUploadResponse>(
      `/sessions/${encodeURIComponent(id)}/workspace/upload${qs(params)}`,
      { method: 'POST', body: formData },
    )
  },

  deleteWorkspaceFile: (id: string, params: { path: string }) =>
    request<WorkspaceDeleteResponse>(
      `/sessions/${encodeURIComponent(id)}/workspace/file${qs(params)}`,
      { method: 'DELETE' },
    ),

  createWorkspaceDirectory: (id: string, body: { path: string }) =>
    request<WorkspaceMkdirResponse>(
      `/sessions/${encodeURIComponent(id)}/workspace/mkdir`,
      { method: 'POST', body: JSON.stringify(body) },
    ),

  moveWorkspaceEntry: (
    id: string,
    body: { src: string; dst: string; overwrite?: boolean },
  ) =>
    request<WorkspaceMoveResponse>(
      `/sessions/${encodeURIComponent(id)}/workspace/move`,
      { method: 'POST', body: JSON.stringify(body) },
    ),

  createWorkspaceFile: (
    id: string,
    body: { path: string; content?: string; overwrite?: boolean },
  ) =>
    request<WorkspaceCreateFileResponse>(
      `/sessions/${encodeURIComponent(id)}/workspace/file`,
      { method: 'POST', body: JSON.stringify(body) },
    ),

  saveWorkspaceFile: (
    id: string,
    body: { path: string; content: string },
  ) =>
    request<WorkspaceSaveFileResponse>(
      `/sessions/${encodeURIComponent(id)}/workspace/file`,
      { method: 'PUT', body: JSON.stringify(body) },
    ),

  deleteWorkspaceDirectory: (
    id: string,
    params: { path: string; recursive?: boolean },
  ) =>
    request<WorkspaceDeleteDirectoryResponse>(
      `/sessions/${encodeURIComponent(id)}/workspace/directory${qs(params)}`,
      { method: 'DELETE' },
    ),

  workspaceDownloadUrl: (id: string, path?: string): string =>
    `${API_BASE}/sessions/${encodeURIComponent(id)}/workspace/download${qs({ path })}`,
}

import type {
  AgentTypesResponse,
  Capabilities,
  ChatImageInput,
  ChatOverrides,
  SessionMessage,
  SessionMemoryResponse,
  SessionMemoryNote,
  SessionMemoryNoteDeleteResponse,
  SessionMemoryNoteKind,
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
  SubagentSummaryListResponse,
  SubagentTimelineResponse,
  SkillListResponse,
  SkillMutationResponse,
  McpStatusResponse,
  McpReloadResponse,
  McpServerConfig,
  McpServersConfigResponse,
  MetricsCurrentSnapshot,
  MetricsHistoryResponse,
  MetricsSessionSnapshot,
  MetricsRange,
  MetricsBucket,
  AlertsActiveResponse,
  AlertsHistoryResponse,
  AlertsRulesResponse,
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
    cache: 'no-store',
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })
  return parseResponse<T>(res)
}

async function requestRaw<T>(path: string, init: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: 'no-store', ...init })
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

  listBrowserTabs: () =>
    request<{ tabs: { targetId: string; title: string; url: string }[] }>(
      '/browser/tabs',
    ),

  createBrowserTab: (body: { url?: string } = {}) =>
    request<{ targetId: string; url: string }>('/browser/tabs', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  closeBrowserTab: (targetId: string) =>
    request<{ targetId: string; closed: boolean }>(
      `/browser/tabs/${encodeURIComponent(targetId)}`,
      { method: 'DELETE' },
    ),

  activateBrowserTab: (targetId: string) =>
    request<{ targetId: string; activated: boolean }>(
      `/browser/tabs/${encodeURIComponent(targetId)}/activate`,
      { method: 'POST' },
    ),

  capabilities: () => request<Capabilities>('/capabilities'),

  agentTypes: () => request<AgentTypesResponse>('/agent-types'),

  listSessions: () => request<{ sessions: SessionSummary[] }>('/sessions'),

  createSession: (
    body: { title?: string; session_id?: string; agent_type?: string } = {},
  ) =>
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

  getSessionMemory: (id: string) =>
    request<SessionMemoryResponse>(
      `/sessions/${encodeURIComponent(id)}/memory`,
    ),

  addSessionMemoryNote: (
    id: string,
    body: { content: string; kind?: SessionMemoryNoteKind },
  ) =>
    request<SessionMemoryNote>(
      `/sessions/${encodeURIComponent(id)}/memory/notes`,
      {
        method: 'POST',
        body: JSON.stringify(body),
      },
    ),

  deleteSessionMemoryNote: (id: string, noteId: number) =>
    request<SessionMemoryNoteDeleteResponse>(
      `/sessions/${encodeURIComponent(id)}/memory/notes/${noteId}`,
      { method: 'DELETE' },
    ),

  clearSessionMemorySummary: (id: string) =>
    request<SessionMemoryResponse>(
      `/sessions/${encodeURIComponent(id)}/memory/summary`,
      { method: 'DELETE' },
    ),

  chat: (body: {
    session_id: string
    message: string
    images?: ChatImageInput[]
    model?: string
  } & ChatOverrides) =>
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

  // Resolve a path the model wrote in markdown (an absolute server path like
  // `/home/.../workspaces/<session>/example.png`, or a workspace-relative one)
  // into a URL the browser can actually fetch. Already-fetchable srcs
  // (http/https/data/blob) are returned untouched.
  workspaceImageUrl: (id: string, rawPath: string): string => {
    if (/^(https?:|data:|blob:)/i.test(rawPath)) return rawPath
    const marker = `/${id}/`
    const idx = rawPath.indexOf(marker)
    const relative = idx >= 0 ? rawPath.slice(idx + marker.length) : rawPath
    return `${API_BASE}/sessions/${encodeURIComponent(id)}/workspace/file/raw${qs({ path: relative })}`
  },

  uploadWorkspaceFiles: (
    id: string,
    params: { path?: string; overwrite?: boolean },
    files: File[],
  ) => {
    const formData = new FormData()
    for (const f of files) {
      formData.append('files', f, f.name)
      // webkitRelativePath is set by the browser when the user picks a folder.
      // We mirror the order so the backend can zip files[i] with relative_paths[i].
      formData.append('relative_paths', (f as File & { webkitRelativePath?: string }).webkitRelativePath || '')
    }
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

  listSubagents: (
    sessionId: string,
    params: { phase?: string; limit?: number } = {},
  ) =>
    request<SubagentSummaryListResponse>(
      `/sessions/${encodeURIComponent(sessionId)}/subagents${qs(params)}`,
    ),

  getSubagentEvents: (
    sessionId: string,
    taskId: string,
    params: { after_seq?: number; limit?: number } = {},
  ) =>
    request<SubagentTimelineResponse>(
      `/sessions/${encodeURIComponent(sessionId)}/subagents/${encodeURIComponent(
        taskId,
      )}/events${qs(params)}`,
    ),

  sessionEventStreamUrl: (sessionId: string): string =>
    `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/events/stream`,

  listSkills: () => request<SkillListResponse>('/skills'),

  createSkill: (body: {
    name: string
    content: string
    files?: { path: string; content_base64: string }[]
  }) =>
    request<SkillMutationResponse>('/skills', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  deleteSkill: (name: string) =>
    request<SkillMutationResponse>(`/skills/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }),

  setSkillDisabled: (name: string, disabled: boolean) =>
    request<SkillMutationResponse>(`/skills/${encodeURIComponent(name)}`, {
      method: 'PATCH',
      body: JSON.stringify({ disabled }),
    }),

  getMcpStatus: () => request<McpStatusResponse>('/mcp/status'),

  reloadMcp: () =>
    request<McpReloadResponse>('/mcp/reload', { method: 'POST' }),

  getMcpServers: () => request<McpServersConfigResponse>('/mcp/servers'),

  upsertMcpServer: (name: string, config: McpServerConfig) =>
    request<McpReloadResponse>(`/mcp/servers/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify(config),
    }),

  deleteMcpServer: (name: string) =>
    request<McpReloadResponse>(`/mcp/servers/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }),

  answerAskUserQuestion: (
    sessionId: string,
    answers: Record<string, string | string[]>,
  ) =>
    request<{ ok: boolean }>(
      `/sessions/${encodeURIComponent(sessionId)}/ask_user_question/answer`,
      { method: 'POST', body: JSON.stringify({ answers }) },
    ),

  metricsCurrent: () => request<MetricsCurrentSnapshot>('/metrics/current'),

  metricsSession: (sessionId: string) =>
    request<MetricsSessionSnapshot>(
      `/metrics/sessions/${encodeURIComponent(sessionId)}`,
    ),

  metricsHistory: (params: {
    range: MetricsRange
    series: string[]
    bucket?: MetricsBucket
  }) =>
    request<MetricsHistoryResponse>(
      `/metrics/history${qs({
        range: params.range,
        series: params.series.join(','),
        bucket: params.bucket,
      })}`,
    ),

  alertsActive: () => request<AlertsActiveResponse>('/alerts/active'),

  alertsHistory: (params: { limit?: number } = {}) =>
    request<AlertsHistoryResponse>(`/alerts/history${qs(params)}`),

  alertsRules: () => request<AlertsRulesResponse>('/alerts/rules'),

  ackAlert: (eventId: number) =>
    request<{ event_id: number; acknowledged: boolean }>(
      `/alerts/${eventId}/ack`,
      { method: 'POST' },
    ),

  silenceAlertRule: (ruleName: string, durationSeconds: number) =>
    request<{ rule_name: string; silenced_until: string }>(
      `/alerts/rules/${encodeURIComponent(ruleName)}/silence`,
      {
        method: 'POST',
        body: JSON.stringify({ duration_seconds: durationSeconds }),
      },
    ),

  unsilenceAlertRule: (ruleName: string) =>
    request<{ rule_name: string; silenced_until: null }>(
      `/alerts/rules/${encodeURIComponent(ruleName)}/silence`,
      { method: 'DELETE' },
    ),
}

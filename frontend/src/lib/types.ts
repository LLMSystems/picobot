export interface ModelInfo {
  provider: string
  name: string
}

export interface ToolCapability {
  name: string
  description: string
  category: string
  dangerous: boolean
}

export interface CapabilityFeatures {
  streaming: boolean
  session_workspace: boolean
  file_upload: boolean
  multimodal: boolean
}

export interface Capabilities {
  model: ModelInfo
  max_iterations: number
  tools: ToolCapability[]
  features: CapabilityFeatures
}

export interface SessionSummary {
  session_id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
  last_user_message: string
  last_assistant_preview: string
}

export type MessageRole = 'user' | 'assistant' | 'tool' | 'system'

export interface ToolCallRef {
  id: string
  type?: string
  function?: { name: string; arguments: string }
}

export type ImageDetail = 'auto' | 'low' | 'high'

export interface ChatImageInput {
  path?: string | null
  url?: string | null
  detail?: ImageDetail
}

export interface SessionMessageImage {
  path?: string | null
  url?: string | null
  detail?: ImageDetail
}

export interface SessionMessageContentTextBlock {
  type: 'text'
  text: string
}

export interface SessionMessageContentImageBlock {
  type: 'image'
  path?: string | null
  url?: string | null
  detail?: ImageDetail
}

export type SessionMessageContentBlock =
  | SessionMessageContentTextBlock
  | SessionMessageContentImageBlock

export interface SessionMessage {
  id: string
  role: MessageRole
  content: string | SessionMessageContentBlock[]
  created_at: string
  tool_calls?: ToolCallRef[]
  tool_call_id?: string
  name?: string
  images?: SessionMessageImage[]
}

export interface ChatUsage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export interface ChatTraceEvent<T = unknown> {
  event: string
  data: T
}

export interface ChatResponse {
  session_id: string
  content: string
  usage: ChatUsage
  tools_used: string[]
  stop_reason: string
  events: ChatTraceEvent[]
}

export interface ApiErrorBody {
  error: { code: string; message: string; request_id: string }
}

export interface RunStartedData {
  session_id: string
  message: string
}

export interface ToolCallStartedData {
  id: string
  name: string
  arguments: Record<string, unknown>
}

export interface ToolCallFinishedData {
  id: string
  name: string
  ok: boolean
  result: unknown
}

export interface DoneData {
  session_id: string
  content: string
  usage: ChatUsage
  tools_used: string[]
  stop_reason: string
}

export interface StreamErrorData {
  code: string
  message: string
  request_id: string
}

export interface DisplayToolCall {
  id: string
  name: string
  arguments: Record<string, unknown>
  result?: unknown
  ok?: boolean
  status: 'running' | 'ok' | 'failed'
}

export type DisplayMessageStatus = 'complete' | 'streaming' | 'aborted' | 'error'

export type DisplayMessageSegment =
  | { type: 'text'; content: string }
  | { type: 'tool'; toolCall: DisplayToolCall }

export interface DisplayMessageImage {
  path?: string | null
  url?: string | null
  detail?: ImageDetail
}

export interface DisplayMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  toolCalls: DisplayToolCall[]
  segments: DisplayMessageSegment[]
  status: DisplayMessageStatus
  usage?: ChatUsage
  toolsUsed?: string[]
  images?: DisplayMessageImage[]
}

export type WorkspaceEntryType = 'file' | 'directory'

export interface WorkspaceEntryDTO {
  path: string
  name: string
  type: WorkspaceEntryType
  size: number | null
  updated_at: string
}

export interface WorkspaceTreeResponse {
  session_id: string
  path: string
  entries: WorkspaceEntryDTO[]
  truncated: boolean
}

export interface WorkspaceFileResponse {
  session_id: string
  path: string
  content: string
  encoding: string
  truncated: boolean
  line_count: number
}

export interface WorkspaceChangedData {
  session_id: string
  paths: string[]
}

export interface WorkspaceUploadedFile {
  path: string
  name: string
  size: number
  content_type: string
  overwritten: boolean
}

export interface WorkspaceSkippedFile {
  name: string
  reason: 'already_exists'
}

export interface WorkspaceUploadResponse {
  session_id: string
  path: string
  uploaded: WorkspaceUploadedFile[]
  skipped: WorkspaceSkippedFile[]
}

export interface WorkspaceDeleteResponse {
  session_id: string
  path: string
  deleted: boolean
}

export interface WorkspaceMkdirResponse {
  session_id: string
  path: string
  created: boolean
}

export interface WorkspaceMoveResponse {
  session_id: string
  src: string
  dst: string
  type: WorkspaceEntryType
  overwritten: boolean
}

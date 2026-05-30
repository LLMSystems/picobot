export interface ModelInfo {
  provider: string
  name: string
}

export interface ToolCapability {
  name: string
  description: string
  category: string
  dangerous: boolean
  display_name?: string | null
  description_zh?: string | null
}

export interface CapabilityFeatures {
  streaming: boolean
  session_workspace: boolean
  file_upload: boolean
  multimodal: boolean
  model_override: boolean
}

export interface Capabilities {
  model: ModelInfo
  available_models: string[]
  default_subagent_model: string | null
  max_iterations: number
  tools: ToolCapability[]
  features: CapabilityFeatures
  default_system_prompt: string
  default_temperature: number
  default_max_tokens: number | null
}

export interface ChatOverrides {
  system_prompt?: string
  temperature?: number
  max_tokens?: number
  max_iterations?: number
  disabled_tools?: string[]
  subagent_model?: string
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

export interface SessionMessageMetadata {
  internal?: boolean
  source?: string
  kind?: string
  task_id?: string
  parent_session_id?: string
  ok?: boolean
  stop_reason?: string | null
  [key: string]: unknown
}

export interface SessionMessage {
  id: string
  role: MessageRole
  content: string | SessionMessageContentBlock[]
  created_at: string
  tool_calls?: ToolCallRef[]
  tool_call_id?: string
  name?: string
  images?: SessionMessageImage[]
  metadata?: SessionMessageMetadata
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

export type TodoStatus = 'pending' | 'in_progress' | 'completed'

export interface TodoItem {
  content: string
  activeForm: string
  status: TodoStatus
}

export interface TodoSnapshot {
  todos: TodoItem[]
  completed: number
  total: number
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

export interface SubagentResultPayload {
  taskId: string
  label: string
  task: string | null
  ok: boolean
  stopReason: string | null
  result: string
  workspace: string | null
}

export interface DisplayMessage {
  id: string
  role: 'user' | 'assistant' | 'subagent_result' | 'todo_summary'
  content: string
  created_at: string
  toolCalls: DisplayToolCall[]
  segments: DisplayMessageSegment[]
  status: DisplayMessageStatus
  usage?: ChatUsage
  toolsUsed?: string[]
  images?: DisplayMessageImage[]
  subagent?: SubagentResultPayload
  todoSnapshot?: TodoSnapshot
}

export type SubagentPhase =
  | 'spawned'
  | 'running'
  | 'done'
  | 'failed'
  | 'cancelled'

export interface SubagentSummary {
  task_id: string
  parent_session_id: string
  label: string
  task: string
  workspace: string | null
  phase: SubagentPhase
  started_at: string
  finished_at: string | null
  stop_reason: string | null
  ok: boolean | null
  error: string | null
  usage: Record<string, number>
  tool_events: Array<Record<string, unknown>>
  final_content: string | null
  model: string | null
}

export interface SubagentSummaryListResponse {
  session_id: string
  items: SubagentSummary[]
}

export interface SubagentTimelineEvent {
  id: number
  task_id: string
  parent_session_id: string
  seq: number
  event_type: string
  created_at: string
  payload: Record<string, unknown>
}

export interface SubagentTimelineResponse {
  session_id: string
  task_id: string
  events: SubagentTimelineEvent[]
}

export interface SubagentLiveEvent {
  session_id: string
  task_id: string
  label: string
  event: string
  data: Record<string, unknown>
  seq: number
  created_at: string
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

export interface WorkspaceCreateFileResponse {
  session_id: string
  path: string
  created: boolean
}

export interface WorkspaceSaveFileResponse {
  session_id: string
  path: string
  saved: boolean
  size: number
  updated_at: string
}

export interface WorkspaceDeleteDirectoryResponse {
  session_id: string
  path: string
  deleted: boolean
}

export interface SkillInfo {
  name: string
  source: 'builtin' | 'custom'
  description: string
  always: boolean
  disabled: boolean
}

export interface SkillListResponse {
  skills: SkillInfo[]
}

export interface SkillMutationResponse {
  name: string
  ok: boolean
}

export interface AskUserQuestionOption {
  label: string
  description: string
}

export interface AskUserQuestion {
  question: string
  header: string
  multiSelect: boolean
  options: AskUserQuestionOption[]
}

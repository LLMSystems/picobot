export interface ModelInfo {
  provider: string
  name: string
}

export interface AuthUser {
  id: number
  username: string
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
  agent_types: boolean
}

export interface AgentType {
  name: string
  display_name: string
  description: string
}

export interface AgentTypesResponse {
  default: string
  agent_types: AgentType[]
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
  agent_type: string | null
  created_at: string
  updated_at: string
  message_count: number
  last_user_message: string
  last_assistant_preview: string
}

export interface SessionMemoryResponse {
  session_id: string
  enabled: boolean
  has_summary: boolean
  summary: string
  compacted_message_count: number
  updated_at: string | null
  notes: SessionMemoryNote[]
}

export type SessionMemoryNoteKind = 'note' | 'preference' | 'correction'

export interface SessionMemoryNote {
  id: number
  session_id: string
  kind: SessionMemoryNoteKind
  content: string
  created_at: string
  updated_at: string
}

export interface SessionMemoryNoteDeleteResponse {
  session_id: string
  note_id: number
  deleted: boolean
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
  reasoning_content?: string
  runtime_notices?: DisplayRuntimeNotice[]
  run_id?: string
  synthetic_image_injection?: boolean
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

export interface ReasoningDeltaData {
  delta: string
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
  | { type: 'reasoning'; content: string }
  | { type: 'text'; content: string }
  | { type: 'tool'; toolCall: DisplayToolCall }
  | { type: 'image'; images: DisplayMessageImage[] }

export interface DisplayMessageImage {
  path?: string | null
  url?: string | null
  detail?: ImageDetail
}

export interface DisplayRuntimeNotice {
  key: string
  kind: 'info' | 'success' | 'warning' | 'error'
  text: string
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
  runtimeNotices?: DisplayRuntimeNotice[]
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

export interface MemoryCompactionStartedData {
  session_id: string
  reason: string
  estimated_tokens: number
  budget_tokens: number
  target_tokens: number
  compacted_message_count_before: number
}

export interface MemoryCompactionFinishedData {
  session_id: string
  compacted_message_count_before: number
  compacted_message_count_after: number
  summary_chars: number
  summary_updated: boolean
}

export interface MemoryCompactionSkippedData {
  session_id: string
  reason: string
  estimated_tokens?: number
  budget_tokens?: number
}

export interface MemoryCompactionFailedData {
  session_id: string
  message: string
  error?: string
}

export interface ImageInjectedData {
  images: { path?: string | null; url?: string | null; detail?: ImageDetail }[]
}

export type ChatRuntimeEvent =
  | { event: 'run_started'; data: RunStartedData }
  | { event: 'image_injected'; data: ImageInjectedData }
  | { event: 'reasoning_delta'; data: ReasoningDeltaData }
  | { event: 'tool_call_started'; data: ToolCallStartedData }
  | { event: 'tool_call_finished'; data: ToolCallFinishedData }
  | { event: 'workspace_changed'; data: WorkspaceChangedData }
  | { event: 'memory_compaction_started'; data: MemoryCompactionStartedData }
  | { event: 'memory_compaction_finished'; data: MemoryCompactionFinishedData }
  | { event: 'memory_compaction_skipped'; data: MemoryCompactionSkippedData }
  | { event: 'memory_compaction_failed'; data: MemoryCompactionFailedData }
  | { event: string; data: unknown }

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

// ---- metrics dashboard ----------------------------------------------------

export interface MetricsSystemBlock {
  cpu_percent: number | null
  rss_bytes: number | null
  threads: number | null
  db_file_bytes: number | null
  db_row_counts: Record<string, number>
  workspace_total_bytes: number | null
  workspace_session_count: number | null
  active_sse_connections: Record<string, number>
  chrome_alive: boolean | null
}

export interface MetricsTopTool {
  name: string
  count: number
  success_rate: number
}

export interface MetricsAgentBlock {
  sessions_total: number
  sessions_active_24h: number
  sessions_new_24h: number
  message_count_total: number
  iterations_total: number
  tool_calls_total: number
  tool_success_rate: number
  top_tools: MetricsTopTool[]
}

export interface MetricsSubagentBlock {
  runs_24h: number
  success_rate_24h: number
  duration_p50_ms: number
  duration_p95_ms: number
  running_now: number
  tokens_in_24h: number
  tokens_out_24h: number
}

export interface MetricsEndpointSummary {
  endpoint: string
  count: number
  latency_p50_ms: number
  latency_p95_ms: number
  error_4xx: number
  error_5xx: number
}

export interface MetricsApiBlock {
  qps_1m: number
  latency_p50_ms: number
  latency_p95_ms: number
  error_4xx_rate_1h: number
  error_5xx_rate_1h: number
  top_endpoints_1h: MetricsEndpointSummary[]
}

export interface MetricsUsageEntry {
  model: string
  tokens_in: number
  tokens_out: number
}

export interface MetricsUsageBlock {
  tokens_in_24h: number
  tokens_out_24h: number
  by_model_24h: MetricsUsageEntry[]
}

export interface MetricsLlmModelEntry {
  model: string
  calls: number
  errors: number
  timeouts: number
  error_rate: number
  timeout_rate: number
  latency_p50_ms: number
  latency_p95_ms: number
  ttft_p50_ms: number
  ttft_p95_ms: number
}

export interface MetricsLlmBlock {
  calls_10m: number
  errors_10m: number
  timeouts_10m: number
  error_rate_10m: number
  timeout_rate_10m: number
  latency_p50_ms: number
  latency_p95_ms: number
  ttft_p50_ms: number
  ttft_p95_ms: number
  iterations_per_chat_avg: number
  iterations_per_chat_max: number
  iterations_per_chat_p95: number
  chats_10m: number
  by_model_10m: MetricsLlmModelEntry[]
}

export interface MetricsCurrentSnapshot {
  ts: string
  system: MetricsSystemBlock
  agent: MetricsAgentBlock
  subagents: MetricsSubagentBlock
  api: MetricsApiBlock
  usage: MetricsUsageBlock
  llm: MetricsLlmBlock
}

export interface MetricsSessionToolBreakdown {
  name: string
  count: number
  success: number
  failure: number
  success_rate: number
}

export type MetricsRange = '1h' | '24h' | '7d'
export type MetricsBucket = '1m' | '5m' | '15m' | '1h' | '1d'

export interface MetricsHistoryPoint {
  ts: string
  value: number | null
}

export interface MetricsHistorySeries {
  metric: string
  category: string
  dim_key: string | null
  dim_value: string | null
  points: MetricsHistoryPoint[]
}

export interface MetricsHistoryResponse {
  range: MetricsRange
  bucket: MetricsBucket
  series: MetricsHistorySeries[]
}

// ---- alerts ----------------------------------------------------------------

export type AlertSeverity = 'info' | 'warning' | 'critical'

export interface AlertRule {
  name: string
  display_name: string | null
  description: string
  severity: AlertSeverity
  metric_path: string
  comparator: string
  threshold: number | boolean | string
  for_seconds: number
}

export interface AlertEvent {
  id: number
  rule_name: string
  display_name: string | null
  severity: AlertSeverity
  description: string
  metric_path: string
  comparator: string
  threshold: string
  fired_at: string
  resolved_at: string | null
  acknowledged_at: string | null
  trigger_value: number | null
  context: Record<string, unknown>
}

export interface AlertsActiveResponse {
  items: AlertEvent[]
  silences: Record<string, string>
}

export interface AlertsHistoryResponse {
  items: AlertEvent[]
}

export interface AlertsRulesResponse {
  rules: AlertRule[]
}

export interface MetricsSessionSnapshot {
  session_id: string
  created_at: string | null
  last_active_at: string | null
  message_count: number
  iterations_total: number
  tool_calls_total: number
  tool_success_rate: number
  tool_breakdown: MetricsSessionToolBreakdown[]
  subagent_runs: number
  subagent_success: number
  subagent_failure: number
  subagent_tokens_in: number
  subagent_tokens_out: number
  subagent_tokens_by_model: Array<{ model: string; tokens_in: number; tokens_out: number }>
  chat_tokens_in: number
  chat_tokens_out: number
  chat_tokens_by_model: MetricsUsageEntry[]
  workspace_bytes: number | null
  workspace_measured_at: number | null
}

export interface McpServerStatus {
  name: string
  transport: string
  connected: boolean
  connecting: boolean
  tool_count: number
  tool_names: string[]
  available_tools: string[]
  enabled_tools: string[]
  include_resources: boolean
  include_prompts: boolean
  error: string | null
}

export interface McpStatusResponse {
  supported: boolean
  reload_supported: boolean
  enabled: boolean
  configured_server_count: number
  connected_server_count: number
  connecting_server_count: number
  tool_count: number
  servers: McpServerStatus[]
}

export interface McpReloadResponse extends McpStatusResponse {
  ok: boolean
  message: string
  added: string[]
  changed: string[]
  removed: string[]
  connected: string[]
  failed: string[]
}

export type McpTransport = 'stdio' | 'sse' | 'streamableHttp'

export interface McpServerConfig {
  type?: McpTransport | null
  command?: string
  args?: string[]
  env?: Record<string, string>
  cwd?: string
  url?: string
  headers?: Record<string, string>
  toolTimeout?: number
  enabledTools?: string[]
  includeResources?: boolean
  includePrompts?: boolean
}

export interface McpServersConfigResponse {
  servers: Record<string, McpServerConfig>
}

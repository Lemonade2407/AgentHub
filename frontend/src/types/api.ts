// 与 AgentHub Contract / DB Design 保持一致的共享 DTO（snake_case，前端不做驼峰转换）

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface Agent {
  id: number
  name: string
  description: string | null
  model: string
  system_prompt: string
  max_steps: number
  enabled: boolean
  tool_ids: number[]
  created_at: string
  updated_at: string
}

export type RunStatus = 'PENDING' | 'RUNNING' | 'SUCCESS' | 'PARTIAL' | 'FAILED' | 'CANCELLED'

export interface RunRead {
  id: string
  agent_id: number
  thread_id: string
  status: RunStatus
  stop_reason: string | null
  input: string
  output: string | null
  error_code: string | null
  error_message: string | null
  max_steps: number
  llm_calls: number
  tool_calls: number
  step_count: number
  duration_ms: number | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

/** SSE 与 Trace 时间线共用的外层字段，契约 §5.3 */
export interface TraceEvent {
  run_id: string
  step_no: number
  event_type: string
  status: string
  node: string | null
  tool: string | null
  duration_ms: number | null
  data: Record<string, unknown> | null
  timestamp: string
}

/** `GET /api/runs/{id}/steps` 的条目，用于回看历史会话 */
export interface StepRead {
  id: number
  run_id: string
  step_no: number
  event_type: string
  status: string
  node: string | null
  tool: string | null
  duration_ms: number | null
  payload: Record<string, unknown>
  created_at: string
}

export const PROVIDERS = [
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'qwen', label: '通义千问' },
  { value: 'custom', label: '自建网关' },
] as const

export function providerLabel(value: string): string {
  return PROVIDERS.find((item) => item.value === value)?.label ?? value
}

// ---------------------------------------------------------------------------
// V2：Model API（修改意见 §3.3）
// ---------------------------------------------------------------------------

export interface ModelApiModel {
  id?: number
  model_key: string
  display_name?: string
  enabled?: boolean
  is_default?: boolean
  capabilities?: Record<string, unknown>
}

export interface ModelApi {
  id: number
  name: string
  provider: string
  base_url: string
  api_key_hint: string | null
  is_default: boolean
  enabled: boolean
  last_test_at: string | null
  last_test_ok: boolean | null
  last_error: string | null
  models?: ModelApiModel[]
  model_api_models?: ModelApiModel[]
}

/** `GET /api/model-apis/available`：Agent 编辑器/选择器用的树形聚合 */
export interface ModelApiOption {
  id: number
  name: string
  provider: string
  models: ModelApiModel[]
}

export interface ModelApiTestResult {
  ok: boolean
  latency_ms: number | null
  models?: string[]
  error?: string | null
}

// ---------------------------------------------------------------------------
// V2：Agent Center（修改意见 §5.4 / §5.5）
// ---------------------------------------------------------------------------

export interface SnapshotSkillRef {
  slug: string
  version: string
  params?: Record<string, unknown>
}

export interface SnapshotToolRef {
  server_name: string
  remote_name: string
  transport?: string
  endpoint?: string
  required?: boolean
}

export interface AgentSnapshot {
  schema_version: number
  agent: {
    name: string
    description?: string | null
    system_prompt: string
    max_steps: number
    required_capabilities?: string[]
  }
  suggested_model?: { provider: string; model_key: string } | null
  skills: SnapshotSkillRef[]
  tools: SnapshotToolRef[]
}

export interface Publication {
  id: number
  title: string
  summary: string
  category: string
  version: string
  status: string
  owner_id?: number
  owner_display_name: string | null
  install_count: number
  like_count: number
  published_at: string | null
  created_at?: string
  snapshot: AgentSnapshot
}

export interface MissingSkill {
  slug: string
  version: string
  params?: Record<string, unknown>
  required: boolean
  reason: string
}

export interface MissingTool {
  server_name: string
  remote_name: string
  required: boolean
  reason: string
}

export interface PrecheckResult {
  publication_id: number
  title: string
  can_install: boolean
  already_installed: boolean
  installed_agent_id: number | null
  resolved_skills: number
  resolved_tools: number
  missing_skills: MissingSkill[]
  missing_tools: MissingTool[]
  warnings: string[]
  suggested_model: { provider: string; model_key: string } | null
}

export interface InstallResult {
  publication_id: number
  agent_id: number
  installed_skill_ids: number[]
  installed_tool_ids: number[]
  missing_skills: MissingSkill[]
  missing_tools: MissingTool[]
  warnings: string[]
  next_steps: string[]
}

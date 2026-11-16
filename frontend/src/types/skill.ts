// Skill / Tool 共享 DTO（与 Contract v2.0 的 snake_case 字段一致）

export interface SkillTool {
  tool_id: number
  qualified_name: string
  server_name: string
  description: string
  required: boolean
  enabled: boolean
}

export interface Skill {
  id: number
  owner_id: number
  owner_display_name: string | null
  name: string
  slug: string
  summary: string
  category: string
  icon: string | null
  version: string
  visibility: string
  status: string
  instructions: string
  input_schema: Record<string, unknown>
  tags: string[]
  install_count: number
  like_count: number
  tools: SkillTool[]
  owned: boolean
  created_at: string
  updated_at: string
}

export interface AgentSkill {
  skill_id: number
  name: string
  slug: string
  version: string
  status: string
  visibility: string
  order_no: number
  enabled: boolean
  params: Record<string, unknown>
  tools: SkillTool[]
}

export interface ToolDefinition {
  id: number
  server_id: number
  server_name: string
  remote_name: string
  qualified_name: string
  description: string
  input_schema: Record<string, unknown>
  risk_level: string
  enabled: boolean
  updated_at: string
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface SkillParameterSpec {
  name: string
  type: string
  required: boolean
  description: string
  default?: unknown
}

export const SKILL_CATEGORIES = [
  { value: 'general', label: '通用' },
  { value: 'writing', label: '写作' },
  { value: 'coding', label: '编码' },
  { value: 'data', label: '数据' },
  { value: 'research', label: '研究' },
  { value: 'ops', label: '运维' },
] as const

export function categoryLabel(value: string): string {
  return SKILL_CATEGORIES.find((item) => item.value === value)?.label ?? value
}

export function statusLabel(value: string): string {
  return { draft: '草稿', published: '已公开', archived: '已下架' }[value] ?? value
}

export function visibilityLabel(value: string): string {
  return value === 'public' ? '公开' : '私有'
}

/** 从 Skill 的 JSON Schema 子集提取参数，用于编辑器的参数表单与预览。 */
export function parametersFromSchema(
  schema: Record<string, unknown> | null | undefined,
): SkillParameterSpec[] {
  if (!schema || typeof schema !== 'object') return []
  const properties = schema.properties
  if (!properties || typeof properties !== 'object') return []
  const required = Array.isArray(schema.required) ? (schema.required as string[]) : []
  return Object.entries(properties as Record<string, unknown>).map(([name, raw]) => {
    const spec = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
    return {
      name,
      type: String(spec.type ?? 'string'),
      required: required.includes(name),
      description: String(spec.description ?? ''),
      default: spec.default,
    }
  })
}

/** 预览：只做 `{{param}}` 字符串替换，不执行任何表达式（与运行期一致）。 */
export function renderInstructions(
  instructions: string,
  values: Record<string, unknown>,
): string {
  return (instructions || '').replace(
    /\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}/g,
    (whole, name: string) => (name in values ? String(values[name]) : whole),
  )
}

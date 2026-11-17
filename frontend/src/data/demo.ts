import type { ModelApi, Publication } from '../types/api'

// 后端 D（WP-1.2 / WP-3.1）接口尚未合并时，前端用于界面走查的演示数据。
// 页面上会显示“演示数据”标识；接口就绪后自动切换为真实数据。

export const DEMO_MODEL_APIS: ModelApi[] = [
  {
    id: 9001,
    name: '我的 DeepSeek',
    provider: 'deepseek',
    base_url: 'https://api.deepseek.com/v1',
    api_key_hint: 'a1b2',
    is_default: true,
    enabled: true,
    last_test_at: new Date(Date.now() - 3_600_000).toISOString(),
    last_test_ok: true,
    last_error: null,
    models: [
      { id: 9101, model_key: 'deepseek-chat', display_name: 'DeepSeek Chat', enabled: true, is_default: true },
      { id: 9102, model_key: 'deepseek-reasoner', display_name: 'DeepSeek Reasoner', enabled: true },
    ],
  },
  {
    id: 9002,
    name: '内网网关',
    provider: 'custom',
    base_url: 'https://llm-gateway.example.com/v1',
    api_key_hint: '9f3c',
    is_default: false,
    enabled: true,
    last_test_at: null,
    last_test_ok: null,
    last_error: null,
    models: [{ id: 9103, model_key: 'qwen-plus', display_name: 'qwen-plus', enabled: true }],
  },
]

export const DEMO_PUBLICATIONS: Publication[] = [
  {
    id: 9201,
    title: '周报助手',
    summary: '把本周 Git 提交与日程整理成结构清晰的周报，支持语气与篇幅参数。',
    category: 'writing',
    version: '1.0.0',
    status: 'published',
    owner_display_name: 'Demo 作者',
    install_count: 128,
    like_count: 32,
    published_at: new Date(Date.now() - 2 * 86_400_000).toISOString(),
    snapshot: {
      schema_version: 1,
      agent: {
        name: '周报助手',
        description: '把本周 Git 与日程整理成周报',
        system_prompt:
          '你是一名严谨的研发助理。请先收集本周提交与日程，再按「本周进展 / 风险 / 下周计划」输出周报，避免编造事实。',
        max_steps: 8,
        required_capabilities: ['tool_call'],
      },
      suggested_model: { provider: 'deepseek', model_key: 'deepseek-chat' },
      skills: [{ slug: 'weekly-report', version: '1.0.0', params: { tone: '正式' } }],
      tools: [
        {
          server_name: 'git-tools',
          remote_name: 'list_commits',
          transport: 'streamable_http',
          endpoint: 'https://example.com/mcp',
          required: true,
        },
        { server_name: 'calendar-tools', remote_name: 'list_events', required: true },
      ],
    },
  },
  {
    id: 9202,
    title: 'Issue 分诊员',
    summary: '检索仓库 issue，按严重程度归类并给出处理建议。',
    category: 'coding',
    version: '1.2.0',
    status: 'published',
    owner_display_name: 'Demo 作者',
    install_count: 76,
    like_count: 19,
    published_at: new Date(Date.now() - 5 * 86_400_000).toISOString(),
    snapshot: {
      schema_version: 1,
      agent: {
        name: 'Issue 分诊员',
        description: '检索并归类仓库 issue',
        system_prompt: '你是开源项目的 issue 分诊助手，请先检索 issue，再按 P0/P1/P2 归类并说明理由。',
        max_steps: 10,
        required_capabilities: ['tool_call'],
      },
      suggested_model: { provider: 'deepseek', model_key: 'deepseek-chat' },
      skills: [],
      tools: [{ server_name: 'github-tools', remote_name: 'search_issues', required: true }],
    },
  },
  {
    id: 9203,
    title: '数据巡检助手',
    summary: '定时检查数据表异常波动，输出排查清单与建议动作。',
    category: 'data',
    version: '0.9.0',
    status: 'published',
    owner_display_name: 'Demo 作者',
    install_count: 41,
    like_count: 8,
    published_at: new Date(Date.now() - 9 * 86_400_000).toISOString(),
    snapshot: {
      schema_version: 1,
      agent: {
        name: '数据巡检助手',
        description: '巡检数据异常波动',
        system_prompt: '你是数据质量巡检助手。先用工具拉取指标，再定位异常区间并给出排查步骤。',
        max_steps: 8,
        required_capabilities: ['tool_call'],
      },
      suggested_model: { provider: 'qwen', model_key: 'qwen-plus' },
      skills: [{ slug: 'data-check', version: '1.0.0' }],
      tools: [{ server_name: 'sql-tools', remote_name: 'run_query', required: true }],
    },
  },
]

export function findDemoPublication(id: number): Publication | undefined {
  return DEMO_PUBLICATIONS.find((item) => item.id === id)
}

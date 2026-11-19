<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { riskLevelLabel } from '../types/skill'

// DTO 与 AgentHub_接口契约文档.md §3.2 / §3.3 / §4.2 一致（snake_case）
interface McpServer {
  id: number
  name: string
  endpoint: string
  transport: string
  description: string | null
  enabled: boolean
  status: string
  tool_count: number
  last_error: string | null
  last_discovered_at: string | null
  created_at: string
  updated_at: string
}

interface McpServerTestResult {
  ok: boolean
  status: string
  latency_ms: number
  server_info: { name?: string } | null
  error_code: string | null
  error_message: string | null
}

interface McpDiscoverResult {
  server_id: number
  status: string
  added: number
  updated: number
  removed: number
  total: number
  duration_ms: number
  error_code: string | null
  error_message: string | null
}

interface ToolDefinition {
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

interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

const servers = ref<McpServer[]>([])
const tools = ref<ToolDefinition[]>([])
const loading = ref(false)
const toolsLoading = ref(false)
const error = ref('')
const successMsg = ref('')

// 新建/编辑表单
const showForm = ref(false)
const editing = ref<McpServer | null>(null)
const saving = ref(false)
const form = ref({
  name: '',
  endpoint: '',
  transport: 'streamable_http',
  description: '',
  enabled: true,
})

// 正在执行 测试/发现 的 server id
const busyServer = ref<number | null>(null)
// tool 测试结果 { toolId: 结果文本 }
const toolResults = ref<Record<number, string>>({})
const busyTool = ref<number | null>(null)
// FR-MCP-07：风险等级可由人工覆盖（自动推断仍由 Discovery 完成）
const RISK_LEVELS = ['READ_ONLY', 'LOW_RISK', 'WRITE', 'HIGH_RISK'] as const

function failMessage(resp: Response): Promise<string> {
  return resp
    .json()
    .catch(() => null)
    .then((b) => b?.message ?? `HTTP ${resp.status}`)
}

async function loadServers() {
  loading.value = true
  error.value = ''
  try {
    const resp = await fetch('/api/mcp/servers?page_size=100')
    if (!resp.ok) throw new Error(await failMessage(resp))
    const data: Page<McpServer> = await resp.json()
    servers.value = data.items
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function loadTools() {
  toolsLoading.value = true
  try {
    const resp = await fetch('/api/mcp/tools?page_size=100')
    if (!resp.ok) return
    const data: Page<ToolDefinition> = await resp.json()
    tools.value = data.items.filter((t) => t.enabled)
  } catch {
    // 工具列表加载失败不阻断页面
  } finally {
    toolsLoading.value = false
  }
}

function openCreate() {
  editing.value = null
  form.value = { name: '', endpoint: '', transport: 'streamable_http', description: '', enabled: true }
  error.value = ''
  showForm.value = true
}

function openEdit(s: McpServer) {
  editing.value = s
  form.value = {
    name: s.name,
    endpoint: s.endpoint,
    transport: s.transport,
    description: s.description ?? '',
    enabled: s.enabled,
  }
  error.value = ''
  showForm.value = true
}

async function submitForm() {
  saving.value = true
  error.value = ''
  successMsg.value = ''
  try {
    if (editing.value) {
      // name 注册后不可修改（契约 §4.2.4），PUT 时不携带
      const { name: _ignored, ...body } = form.value
      const resp = await fetch(`/api/mcp/servers/${editing.value.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!resp.ok) throw new Error(await failMessage(resp))
      successMsg.value = '保存成功，建议重新测试与发现'
    } else {
      const resp = await fetch('/api/mcp/servers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form.value),
      })
      if (!resp.ok) throw new Error(await failMessage(resp))
      successMsg.value = '注册成功，建议立即测试并发现工具'
    }
    showForm.value = false
    await loadServers()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

async function testServer(s: McpServer) {
  busyServer.value = s.id
  error.value = ''
  successMsg.value = ''
  try {
    const resp = await fetch(`/api/mcp/servers/${s.id}/test`, { method: 'POST' })
    if (!resp.ok) throw new Error(await failMessage(resp))
    const r: McpServerTestResult = await resp.json()
    if (r.ok) {
      successMsg.value = `测试通过：${r.latency_ms}ms · serverInfo=${r.server_info?.name ?? '-'}`
    } else {
      error.value = `测试失败：${r.error_message ?? r.error_code ?? '未知错误'}`
    }
    await loadServers()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busyServer.value = null
  }
}

async function discover(s: McpServer) {
  busyServer.value = s.id
  error.value = ''
  successMsg.value = ''
  try {
    const resp = await fetch(`/api/mcp/servers/${s.id}/discover`, { method: 'POST' })
    if (!resp.ok) throw new Error(await failMessage(resp))
    const r: McpDiscoverResult = await resp.json()
    if (r.error_code) {
      error.value = `发现失败：${r.error_message ?? r.error_code}`
    } else {
      successMsg.value = `发现完成：新增 ${r.added} · 更新 ${r.updated} · 共 ${r.total} 个工具`
    }
    await loadServers()
    await loadTools()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busyServer.value = null
  }
}

async function testTool(t: ToolDefinition) {
  busyTool.value = t.id
  toolResults.value[t.id] = '测试中…'
  try {
    const resp = await fetch(`/api/mcp/tools/${t.id}/test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ arguments: {} }),
    })
    if (!resp.ok) {
      toolResults.value[t.id] = await failMessage(resp)
      return
    }
    const r: { ok: boolean; duration_ms: number; error_code: string | null; error_message: string | null } =
      await resp.json()
    toolResults.value[t.id] = r.ok ? `调用成功 · ${r.duration_ms}ms` : `调用失败：${r.error_message ?? r.error_code}`
  } catch (e) {
    toolResults.value[t.id] = e instanceof Error ? e.message : String(e)
  } finally {
    busyTool.value = null
  }
}

async function updateRisk(t: ToolDefinition, level: string) {
  if (level === t.risk_level) return
  busyTool.value = t.id
  error.value = ''
  successMsg.value = ''
  try {
    const resp = await fetch(`/api/mcp/tools/${t.id}/risk`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ risk_level: level }),
    })
    if (!resp.ok) throw new Error(await failMessage(resp))
    const updated: ToolDefinition = await resp.json()
    const index = tools.value.findIndex((item) => item.id === t.id)
    if (index >= 0) tools.value[index] = updated
    successMsg.value = `已将 ${t.qualified_name} 的风险等级改为 ${riskLevelLabel(updated.risk_level)}`
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    await loadTools() // 失败时重新拉取，回滚下拉框显示
  } finally {
    busyTool.value = null
  }
}

function statusClass(status: string): string {
  if (status === 'CONNECTED') return 'on'
  if (status === 'ERROR') return 'error'
  return 'unknown'
}

onMounted(() => {
  loadServers()
  loadTools()
})
</script>

<template>
  <section class="page">
    <header class="page-header">
      <h1 class="page-title">MCP Hub</h1>
      <button class="btn-primary" @click="openCreate">注册 Server</button>
    </header>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="successMsg" class="ok">{{ successMsg }}</p>
    <p v-if="loading" class="muted">加载中…</p>

    <div v-if="!loading && servers.length" class="grid">
      <article v-for="s in servers" :key="s.id" class="mcp-card">
        <div class="card-head">
          <div class="title-block">
            <h3>{{ s.name }}</h3>
            <code class="endpoint">{{ s.endpoint }}</code>
          </div>
          <span class="badge" :class="statusClass(s.status)">{{ s.status }}</span>
        </div>

        <div class="facts">
          <span>{{ s.transport }}</span>
          <span>{{ s.tool_count }} 工具</span>
          <span>{{ s.enabled ? '启用' : '停用' }}</span>
        </div>

        <div class="card-foot">
          <span class="muted">#{{ s.id }}</span>
          <div class="ops">
            <button class="btn btn-sm" :disabled="busyServer === s.id" @click="testServer(s)">
              {{ busyServer === s.id ? '测试中…' : '测试连接' }}
            </button>
            <button class="btn btn-sm" :disabled="busyServer === s.id" @click="discover(s)">
              发现工具
            </button>
            <button class="btn btn-sm" @click="openEdit(s)">编辑</button>
          </div>
        </div>
      </article>
    </div>
    <p v-else-if="!loading" class="muted">还没有 Server，点击右上角「注册 Server」添加。</p>

    <h2 class="sub-title">已发现的工具（{{ tools.length }}）</h2>
    <p v-if="toolsLoading" class="muted">加载中…</p>
    <div v-if="!toolsLoading && tools.length" class="grid">
      <article v-for="t in tools" :key="t.id" class="tool-card">
        <div class="card-head">
          <code class="tool-name">{{ t.qualified_name }}</code>
          <span class="risk" :class="t.risk_level.toLowerCase()">{{ riskLevelLabel(t.risk_level) }}</span>
        </div>

        <p class="desc">{{ t.description || '暂无描述' }}</p>

        <div class="facts">
          <span>{{ t.server_name }}</span>
          <select
            class="risk-select"
            :value="t.risk_level"
            :disabled="busyTool === t.id"
            title="人工覆盖风险等级"
            @change="updateRisk(t, ($event.target as HTMLSelectElement).value)"
          >
            <option v-for="level in RISK_LEVELS" :key="level" :value="level">{{ riskLevelLabel(level) }}</option>
          </select>
        </div>

        <div class="card-foot">
          <span class="muted test-result">{{ toolResults[t.id] || '' }}</span>
          <button class="btn btn-sm" :disabled="busyTool === t.id" @click="testTool(t)">测试</button>
        </div>
      </article>
    </div>
    <p v-else-if="!toolsLoading" class="muted">还没有工具，对 Server 执行「发现工具」即可添加。</p>

    <!-- 新建 / 编辑 弹窗 -->
    <div v-if="showForm" class="overlay" @click.self="showForm = false">
      <form class="modal" @submit.prevent="submitForm">
        <h3>{{ editing ? `编辑 Server #${editing.id}` : '注册 MCP Server' }}</h3>

        <div class="row">
          <label>名称（唯一，注册后不可修改）</label>
          <input v-model="form.name" type="text" maxlength="64" :disabled="!!editing" required />
        </div>

        <div class="row">
          <label>Endpoint</label>
          <input v-model="form.endpoint" type="text" maxlength="512" placeholder="例如：https://example.com/mcp" required />
        </div>

        <div class="row">
          <label>传输方式（当前仅支持 Streamable HTTP）</label>
          <select v-model="form.transport">
            <option value="streamable_http">streamable_http</option>
            <option value="stdio" disabled>stdio（暂不支持）</option>
          </select>
        </div>

        <div class="row">
          <label>描述</label>
          <input v-model="form.description" type="text" maxlength="512" />
        </div>

        <div class="row inline">
          <label>启用</label>
          <input v-model="form.enabled" type="checkbox" />
        </div>

        <div class="actions">
          <button class="btn-primary" type="submit" :disabled="saving">
            {{ saving ? '保存中…' : '保存' }}
          </button>
          <button class="btn" type="button" @click="showForm = false">取消</button>
        </div>
      </form>
    </div>
  </section>
</template>

<style scoped>
.sub-title {
  font-size: 16px;
  margin: 24px 0 8px;
}

.mcp-card,
.tool-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 16px;
  transition: border-color 0.15s ease;
}

.mcp-card:hover,
.tool-card:hover {
  border-color: var(--border-strong);
}

.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.title-block {
  min-width: 0;
}

.title-block h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  word-break: break-word;
}

.endpoint {
  display: block;
  margin-top: 2px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-name {
  font-size: 12px;
  color: var(--text-main);
  word-break: break-all;
}

.facts {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  font-size: 11.5px;
  color: var(--text-secondary);
}

.card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid var(--border-color);
}

.tool-card .desc {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 38px;
}

.test-result {
  font-size: 11px;
}

.ops {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.badge {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
}

.badge.on {
  background: var(--success-soft);
  color: var(--success);
}

.badge.error {
  background: var(--danger-soft);
  color: var(--danger);
}

.badge.unknown {
  background: var(--bg-elevated);
  color: var(--text-muted);
}

.risk-select {
  padding: 2px 4px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-panel);
  font-size: 11px;
  color: var(--text-muted);
}

.risk {
  padding: 1px 6px;
  border-radius: 8px;
  font-size: 11px;
}

.risk.read_only {
  background: var(--success-soft);
  color: var(--success);
}

.risk.low_risk {
  background: var(--warn-soft);
  color: var(--warn);
}

.risk.write {
  background: var(--danger-soft);
  color: var(--danger);
}

.risk.high_risk {
  background: var(--danger-soft);
  color: var(--danger);
}

.test-result {
  margin-left: 8px;
  font-size: 12px;
}

.btn {
  padding: 6px 12px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-panel);
  cursor: pointer;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  padding: 6px 14px;
  border: none;
  border-radius: 6px;
  background: var(--accent);
  color: #fff;
  cursor: pointer;
}

.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal {
  width: 480px;
  background: var(--bg-panel);
  border-radius: 10px;
  padding: 20px;
}

.modal h3 {
  margin: 0 0 16px;
}

.row {
  margin-bottom: 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.row.inline {
  flex-direction: row;
  align-items: center;
  gap: 12px;
}

.row label {
  font-weight: 600;
  font-size: 14px;
}

.row input[type='text'],
.row select {
  padding: 8px 10px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
}

.actions {
  display: flex;
  gap: 10px;
  margin-top: 8px;
}

.error {
  color: var(--danger);
}

.ok {
  color: var(--success);
}
</style>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

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
    <div class="header">
      <h1>MCP Center</h1>
      <button class="btn-primary" @click="openCreate">注册 Server</button>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="successMsg" class="ok">{{ successMsg }}</p>
    <p v-if="loading" class="muted">加载中…</p>

    <table v-if="!loading && servers.length" class="table">
      <thead>
        <tr>
          <th>ID</th>
          <th>名称</th>
          <th>Endpoint</th>
          <th>传输</th>
          <th>状态</th>
          <th>工具数</th>
          <th>启用</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="s in servers" :key="s.id">
          <td>{{ s.id }}</td>
          <td>{{ s.name }}</td>
          <td><code>{{ s.endpoint }}</code></td>
          <td>{{ s.transport }}</td>
          <td>
            <span class="badge" :class="statusClass(s.status)">{{ s.status }}</span>
          </td>
          <td>{{ s.tool_count }}</td>
          <td>{{ s.enabled ? '是' : '否' }}</td>
          <td class="ops">
            <button class="btn" :disabled="busyServer === s.id" @click="testServer(s)">
              {{ busyServer === s.id ? '…' : '测试' }}
            </button>
            <button class="btn" :disabled="busyServer === s.id" @click="discover(s)">发现工具</button>
            <button class="btn" @click="openEdit(s)">编辑</button>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-else-if="!loading" class="muted">暂无 Server，点击"注册 Server"添加。</p>

    <h2 class="sub-title">已发现的工具（{{ tools.length }}）</h2>
    <p v-if="toolsLoading" class="muted">加载中…</p>
    <table v-if="!toolsLoading && tools.length" class="table">
      <thead>
        <tr>
          <th>工具名</th>
          <th>Server</th>
          <th>风险级别</th>
          <th>描述</th>
          <th>测试</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="t in tools" :key="t.id">
          <td><code>{{ t.qualified_name }}</code></td>
          <td>{{ t.server_name }}</td>
          <td><span class="risk" :class="t.risk_level.toLowerCase()">{{ t.risk_level }}</span></td>
          <td class="desc">{{ t.description }}</td>
          <td>
            <button class="btn" :disabled="busyTool === t.id" @click="testTool(t)">测试</button>
            <span v-if="toolResults[t.id]" class="muted test-result">{{ toolResults[t.id] }}</span>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-else-if="!toolsLoading" class="muted">暂无工具，对 Server 执行"发现工具"即可入库。</p>

    <!-- 新建 / 编辑 弹窗 -->
    <div v-if="showForm" class="overlay" @click.self="showForm = false">
      <form class="modal" @submit.prevent="submitForm">
        <h3>{{ editing ? `编辑 Server #${editing.id}` : '注册 MCP Server' }}</h3>

        <div class="row">
          <label>名称 *（唯一，注册后不可修改）</label>
          <input v-model="form.name" type="text" maxlength="64" :disabled="!!editing" required />
        </div>

        <div class="row">
          <label>Endpoint *</label>
          <input v-model="form.endpoint" type="text" maxlength="512" placeholder="http://demo-mcp:8100/mcp" required />
        </div>

        <div class="row">
          <label>传输方式（V1 仅支持 Streamable HTTP）</label>
          <select v-model="form.transport">
            <option value="streamable_http">streamable_http</option>
            <option value="stdio" disabled title="P2 再支持">stdio（暂不支持）</option>
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
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.sub-title {
  font-size: 16px;
  margin: 24px 0 8px;
}

.table {
  width: 100%;
  border-collapse: collapse;
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;
}

.table th,
.table td {
  padding: 10px 12px;
  text-align: left;
  border-bottom: 1px solid var(--border-color);
  font-size: 14px;
}

.table th {
  background: var(--surface-muted);
  font-weight: 600;
  color: var(--text-muted);
}

.desc {
  max-width: 320px;
  color: var(--text-muted);
  font-size: 13px;
}

.ops {
  display: flex;
  gap: 6px;
}

.badge {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
}

.badge.on {
  background: #e6f4ea;
  color: #1a7f37;
}

.badge.error {
  background: #ffebe9;
  color: #cf222e;
}

.badge.unknown {
  background: #f0f2f5;
  color: #6e7781;
}

.risk {
  padding: 1px 6px;
  border-radius: 8px;
  font-size: 11px;
}

.risk.read_only {
  background: #e6f4ea;
  color: #1a7f37;
}

.risk.low_risk {
  background: #fff8c5;
  color: #7d4e00;
}

.risk.write {
  background: #ffebe9;
  color: #cf222e;
}

.risk.high_risk {
  background: #ffebe9;
  color: #cf222e;
}

.test-result {
  margin-left: 8px;
  font-size: 12px;
}

.btn {
  padding: 6px 12px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: #fff;
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
  background: #1a7f37;
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
  background: #fff;
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
  color: #d1242f;
}

.ok {
  color: #1a7f37;
}
</style>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

// DTO 与 AgentHub_接口契约文档.md §3.1 / §4.1 一致（snake_case）
interface Agent {
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

const route = useRoute()
const router = useRouter()

const rawId = computed(() => {
  const v = route.params.id
  return Array.isArray(v) ? v[0] : v
})
const isEdit = computed(() => rawId.value !== 'new')

const form = ref({
  name: '',
  description: '',
  model: 'deepseek/deepseek-chat',
  system_prompt: '',
  max_steps: 8,
  enabled: true,
  tool_ids: [] as number[],
})

const tools = ref<ToolDefinition[]>([])
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const successMsg = ref('')

// 模型为自由字符串，V1 约定 provider/model 形式（契约 §2.8）
const commonModels = ['deepseek/deepseek-chat', 'openai/gpt-4o-mini', 'qwen/qwen-plus']

function failMessage(resp: Response): Promise<string> {
  return resp
    .json()
    .catch(() => null)
    .then((b) => b?.message ?? `HTTP ${resp.status}`)
}

async function loadAgent() {
  if (!isEdit.value) return
  loading.value = true
  error.value = ''
  try {
    const resp = await fetch(`/api/agents/${rawId.value}`)
    if (!resp.ok) throw new Error(await failMessage(resp))
    const a: Agent = await resp.json()
    form.value = {
      name: a.name,
      description: a.description ?? '',
      model: a.model,
      system_prompt: a.system_prompt,
      max_steps: a.max_steps,
      enabled: a.enabled,
      tool_ids: [...a.tool_ids],
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function loadTools() {
  try {
    const resp = await fetch('/api/mcp/tools?page_size=100')
    if (!resp.ok) return
    const data: Page<ToolDefinition> = await resp.json()
    tools.value = data.items.filter((t) => t.enabled)
  } catch {
    // 工具列表加载失败不阻断表单
  }
}

function toggleTool(id: number) {
  const i = form.value.tool_ids.indexOf(id)
  if (i >= 0) form.value.tool_ids.splice(i, 1)
  else form.value.tool_ids.push(id)
}

async function save() {
  saving.value = true
  error.value = ''
  successMsg.value = ''
  try {
    if (!isEdit.value) {
      // 新建：POST AgentCreate（含 tool_ids）
      const resp = await fetch('/api/agents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form.value),
      })
      if (!resp.ok) throw new Error(await failMessage(resp))
      const created: Agent = await resp.json()
      successMsg.value = `创建成功 #${created.id}`
      router.replace(`/agents/${created.id}`) // 切到编辑模式，继续可改
    } else {
      // 更新：AgentUpdate 部分更新；tool_ids 走独立接口（全量覆盖，契约 §4.1.6）
      const { tool_ids, ...agentFields } = form.value
      const resp = await fetch(`/api/agents/${rawId.value}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(agentFields),
      })
      if (!resp.ok) throw new Error(await failMessage(resp))
      const toolsResp = await fetch(`/api/agents/${rawId.value}/tools`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool_ids }),
      })
      if (!toolsResp.ok) throw new Error(await failMessage(toolsResp))
      successMsg.value = '保存成功'
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

function goBack() {
  router.push('/agents')
}

onMounted(() => {
  loadAgent()
  loadTools()
})
</script>

<template>
  <section class="page">
    <h1>{{ isEdit ? `编辑 Agent #${rawId}` : '新建 Agent' }}</h1>

    <p v-if="loading" class="muted">加载中…</p>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="successMsg" class="ok">{{ successMsg }}</p>

    <form v-if="!loading" class="form" @submit.prevent="save">
      <div class="row">
        <label>名称 *</label>
        <input v-model="form.name" type="text" maxlength="64" required />
      </div>

      <div class="row">
        <label>描述</label>
        <input v-model="form.description" type="text" maxlength="512" />
      </div>

      <div class="row">
        <label>模型 *</label>
        <input v-model="form.model" type="text" maxlength="128" required list="model-options" />
        <datalist id="model-options">
          <option v-for="m in commonModels" :key="m" :value="m" />
        </datalist>
      </div>

      <div class="row">
        <label>System Prompt</label>
        <textarea v-model="form.system_prompt" rows="6" maxlength="8000"></textarea>
      </div>

      <div class="row inline">
        <label>最大执行步数</label>
        <input v-model.number="form.max_steps" type="number" min="1" max="20" />
        <span class="muted">1 ~ 20，默认 8</span>
      </div>

      <div class="row inline">
        <label>启用</label>
        <input v-model="form.enabled" type="checkbox" />
      </div>

      <div class="row">
        <label>绑定 MCP 工具</label>
        <div v-if="tools.length" class="tool-list">
          <label v-for="t in tools" :key="t.id" class="tool-item">
            <input type="checkbox" :checked="form.tool_ids.includes(t.id)" @change="toggleTool(t.id)" />
            <span class="tool-name">
              <code>{{ t.qualified_name }}</code>
              <span class="risk" :class="t.risk_level.toLowerCase()">{{ t.risk_level }}</span>
            </span>
            <span class="muted">{{ t.description }}</span>
          </label>
        </div>
        <p v-else class="muted">暂无可用工具，请先在 MCP Center 完成 Server 发现。</p>
      </div>

      <div class="actions">
        <button class="btn-primary" type="submit" :disabled="saving">
          {{ saving ? '保存中…' : '保存' }}
        </button>
        <button class="btn" type="button" @click="goBack">返回列表</button>
      </div>
    </form>
  </section>
</template>

<style scoped>
.form {
  max-width: 640px;
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 20px;
}

.row {
  margin-bottom: 16px;
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
.row input[type='number'] {
  padding: 8px 10px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
}

.row textarea {
  padding: 8px 10px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-family: inherit;
}

.tool-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tool-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-size: 13px;
}

.tool-name {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 200px;
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

.actions {
  display: flex;
  gap: 10px;
  margin-top: 8px;
}

.btn {
  padding: 8px 14px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: #fff;
  cursor: pointer;
}

.btn-primary {
  padding: 8px 14px;
  border: none;
  border-radius: 6px;
  background: #1a7f37;
  color: #fff;
  cursor: pointer;
}

.btn:disabled,
.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.error {
  color: #d1242f;
}

.ok {
  color: #1a7f37;
}
</style>

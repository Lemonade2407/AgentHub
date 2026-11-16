<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  statusLabel,
  type AgentSkill,
  type Page,
  type Skill,
  type ToolDefinition,
} from '../types/skill'

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

interface AgentSkillDraft extends AgentSkill {
  params_text: string
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

// ---- V2：Skill 挂载 ----
const agentSkills = ref<AgentSkillDraft[]>([])
const availableSkills = ref<Skill[]>([])
const newSkillId = ref<number | null>(null)
const skillsLoading = ref(false)
const skillsSaving = ref(false)
const skillsMsg = ref('')

const mountedSkillIds = computed(() => new Set(agentSkills.value.map((item) => item.skill_id)))
const selectableSkills = computed(() =>
  availableSkills.value.filter((skill) => !mountedSkillIds.value.has(skill.id)),
)
// 由 Skill 自动带入的工具：以只读标签展示，避免与显式绑定混淆
const skillContributedTools = computed(() => {
  const map = new Map<string, string>()
  for (const skill of agentSkills.value) {
    if (!skill.enabled) continue
    for (const tool of skill.tools) map.set(tool.qualified_name, skill.name)
  }
  return map
})

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

// ---- V2：Skill 挂载 ----

function toDraft(skill: AgentSkill): AgentSkillDraft {
  return { ...skill, params_text: JSON.stringify(skill.params ?? {}, null, 0) }
}

async function loadAgentSkills() {
  if (!isEdit.value) return
  skillsLoading.value = true
  try {
    const [mineResp, mountedResp] = await Promise.all([
      fetch('/api/skills?page_size=100'),
      fetch(`/api/agents/${rawId.value}/skills`),
    ])
    if (mineResp.ok) {
      const data: Page<Skill> = await mineResp.json()
      availableSkills.value = data.items
    }
    if (mountedResp.ok) {
      const data: AgentSkill[] = await mountedResp.json()
      agentSkills.value = data.map(toDraft)
    }
  } catch {
    // Skill 列表失败不阻断 Agent 基础表单
  } finally {
    skillsLoading.value = false
  }
}

function addSkill() {
  if (newSkillId.value == null) return
  const skill = availableSkills.value.find((item) => item.id === newSkillId.value)
  if (!skill || mountedSkillIds.value.has(skill.id)) return
  agentSkills.value.push({
    skill_id: skill.id,
    name: skill.name,
    slug: skill.slug,
    version: skill.version,
    status: skill.status,
    visibility: skill.visibility,
    order_no: agentSkills.value.length,
    enabled: true,
    params: {},
    tools: skill.tools,
    params_text: '{}',
  })
  newSkillId.value = null
}

function removeSkill(index: number) {
  agentSkills.value.splice(index, 1)
}

function moveSkill(index: number, delta: number) {
  const target = index + delta
  if (target < 0 || target >= agentSkills.value.length) return
  const list = agentSkills.value
  ;[list[index], list[target]] = [list[target], list[index]]
}

function parseParams(skill: AgentSkillDraft): Record<string, unknown> {
  const text = skill.params_text.trim()
  if (!text) return {}
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    throw new Error(`Skill「${skill.name}」的参数不是合法 JSON`)
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`Skill「${skill.name}」的参数必须是 JSON 对象`)
  }
  return parsed as Record<string, unknown>
}

async function saveSkills() {
  skillsMsg.value = ''
  error.value = ''
  skillsSaving.value = true
  try {
    const payload = {
      skills: agentSkills.value.map((skill, index) => ({
        skill_id: skill.skill_id,
        order_no: index,
        enabled: skill.enabled,
        params: parseParams(skill),
      })),
    }
    const resp = await fetch(`/api/agents/${rawId.value}/skills`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!resp.ok) throw new Error(await failMessage(resp))
    const data: AgentSkill[] = await resp.json()
    agentSkills.value = data.map(toDraft)
    skillsMsg.value = 'Skills 已保存，运行时会按顺序注入'
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    skillsSaving.value = false
  }
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
      await router.replace(`/agents/${created.id}`) // 切到编辑模式，继续可改
      await loadAgentSkills()
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
  loadAgentSkills()
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
            <input
              type="checkbox"
              :checked="form.tool_ids.includes(t.id)"
              :disabled="skillContributedTools.has(t.qualified_name)"
              @change="toggleTool(t.id)"
            />
            <span class="tool-name">
              <code>{{ t.qualified_name }}</code>
              <span class="risk" :class="t.risk_level.toLowerCase()">{{ t.risk_level }}</span>
            </span>
            <span class="muted desc">{{ t.description }}</span>
            <span v-if="skillContributedTools.has(t.qualified_name)" class="skill-source">
              来自 Skill「{{ skillContributedTools.get(t.qualified_name) }}」，自动进入候选池
            </span>
          </label>
        </div>
        <p v-else class="muted">暂无可用工具，请先在 MCP Center 完成 Server 发现。</p>
      </div>

      <div class="row">
        <label>挂载 Skills</label>
        <p v-if="!isEdit" class="muted">保存 Agent 后可挂载 Skill。</p>
        <template v-else>
          <div class="skill-add">
            <select v-model.number="newSkillId">
              <option :value="null">选择要挂载的 Skill</option>
              <option v-for="s in selectableSkills" :key="s.id" :value="s.id">
                {{ s.name }} · v{{ s.version }}
              </option>
            </select>
            <button class="btn" type="button" @click="addSkill">挂载</button>
            <router-link to="/skills" class="btn" target="_blank">管理 Skills</router-link>
          </div>

          <p v-if="skillsLoading" class="muted">加载中…</p>

          <div v-if="agentSkills.length" class="skill-list">
            <div v-for="(s, index) in agentSkills" :key="s.skill_id" class="skill-item">
              <div class="skill-head">
                <strong>{{ index + 1 }}. {{ s.name }}</strong>
                <code class="muted">{{ s.slug }} · v{{ s.version }}</code>
                <span class="badge" :class="s.status">{{ statusLabel(s.status) }}</span>
                <label class="inline-check">
                  <input v-model="s.enabled" type="checkbox" />
                  启用
                </label>
                <span class="spacer"></span>
                <button
                  class="btn tiny"
                  type="button"
                  :disabled="index === 0"
                  @click="moveSkill(index, -1)"
                >
                  ↑
                </button>
                <button
                  class="btn tiny"
                  type="button"
                  :disabled="index === agentSkills.length - 1"
                  @click="moveSkill(index, 1)"
                >
                  ↓
                </button>
                <button class="btn tiny danger" type="button" @click="removeSkill(index)">
                  移除
                </button>
              </div>

              <div v-if="s.tools.length" class="skill-tools">
                <span class="muted">Skill 工具：</span>
                <span v-for="t in s.tools" :key="t.tool_id" class="tag" :class="{ off: !t.enabled }">
                  {{ t.qualified_name }}
                </span>
              </div>

              <label class="params">
                <span>参数覆盖（JSON，覆盖 Skill 默认值）</span>
                <input v-model="s.params_text" type="text" placeholder='{"tone":"正式"}' />
              </label>
            </div>
          </div>
          <p v-else-if="!skillsLoading" class="muted">
            尚未挂载 Skill。Skill 指令会按顺序追加到 System Prompt，工具自动进入候选池。
          </p>

          <div class="skill-actions">
            <button class="btn-primary" type="button" :disabled="skillsSaving" @click="saveSkills">
              {{ skillsSaving ? '保存中…' : '保存 Skills' }}
            </button>
            <span v-if="skillsMsg" class="ok">{{ skillsMsg }}</span>
          </div>
        </template>
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
  max-width: 760px;
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
  flex-wrap: wrap;
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

.tool-item .desc {
  flex: 1;
  min-width: 160px;
}

.skill-source {
  flex-basis: 100%;
  padding-left: 24px;
  font-size: 12px;
  color: #0969da;
}

.skill-add {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.skill-add select {
  padding: 7px 10px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: #fff;
  min-width: 220px;
}

.skill-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.skill-item {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.skill-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.skill-head code {
  font-size: 12px;
}

.inline-check {
  display: flex !important;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 400 !important;
}

.spacer {
  flex: 1;
}

.btn.tiny {
  padding: 2px 8px;
  font-size: 12px;
}

.btn.tiny.danger {
  color: #cf222e;
  border-color: #ffcecb;
}

.skill-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}

.tag {
  padding: 1px 8px;
  border-radius: 10px;
  background: var(--surface-muted);
  color: #444;
  font-size: 12px;
}

.tag.off {
  color: #cf222e;
  text-decoration: line-through;
}

.params {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.params span {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-muted);
}

.params input {
  padding: 6px 8px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
}

.skill-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.badge {
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
}

.badge.draft {
  background: #f0f2f5;
  color: #6e7781;
}

.badge.published {
  background: #e6f4ea;
  color: #1a7f37;
}

.badge.archived {
  background: #fff8c5;
  color: #7d4e00;
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

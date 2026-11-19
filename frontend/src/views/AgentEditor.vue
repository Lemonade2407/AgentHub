<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errorMessage } from '../api/http'
import ModelSelector from '../components/ModelSelector.vue'
import PublishDialog from '../components/PublishDialog.vue'
import RunPanel from '../components/RunPanel.vue'
import { DOCUMENT_ACCEPT, extractDocumentText } from '../utils/document-text'
import type { Agent } from '../types/api'
import {
  riskLevelLabel,
  statusLabel,
  type AgentSkill,
  type Page,
  type Skill,
  type ToolDefinition,
} from '../types/skill'

type TabKey = 'basic' | 'model' | 'skills' | 'tools' | 'debug'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'basic', label: '基础' },
  { key: 'model', label: '模型' },
  { key: 'skills', label: 'Skills' },
  { key: 'tools', label: '工具' },
  { key: 'debug', label: '调试' },
]

interface AgentSkillDraft extends AgentSkill {
  params_text: string
}

const route = useRoute()
const router = useRouter()

const rawId = computed(() => {
  const value = route.params.id
  return Array.isArray(value) ? value[0] : value
})
const isEdit = computed(() => rawId.value !== 'new')
const agentId = computed(() => Number(rawId.value))

const activeTab = ref<TabKey>('basic')

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
const publishOpen = ref(false)

// System Prompt 文档导入（浏览器本地解析，不上传文件）
const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
const uploadMessage = ref('')
const uploadOk = ref(true)

const MAX_PROMPT_LENGTH = 8000

// Skill 挂载
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
const skillContributedTools = computed(() => {
  const map = new Map<string, string>()
  for (const skill of agentSkills.value) {
    if (!skill.enabled) continue
    for (const tool of skill.tools) map.set(tool.qualified_name, skill.name)
  }
  return map
})


async function loadAgent() {
  if (!isEdit.value) return
  loading.value = true
  error.value = ''
  try {
    const agent = await api.get<Agent>(`/api/agents/${rawId.value}`)
    form.value = {
      name: agent.name,
      description: agent.description ?? '',
      model: agent.model,
      system_prompt: agent.system_prompt,
      max_steps: agent.max_steps,
      enabled: agent.enabled,
      tool_ids: [...agent.tool_ids],
    }
  } catch (e) {
    error.value = errorMessage(e, 'Agent 加载失败')
  } finally {
    loading.value = false
  }
}

async function onDocumentSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return

  uploadMessage.value = ''
  if (file.size > 10 * 1024 * 1024) {
    uploadOk.value = false
    uploadMessage.value = '文件不能超过 10MB'
    return
  }

  uploading.value = true
  try {
    const raw = await extractDocumentText(file)
    const text = raw.replace(/\r\n/g, '\n').trim()
    if (!text) {
      throw new Error('未解析到文字，扫描版 PDF 暂不支持')
    }

    const current = form.value.system_prompt.trimEnd()
    const header = current ? `\n\n--- 文档：${file.name} ---\n` : ''
    const available = MAX_PROMPT_LENGTH - current.length - header.length
    if (available <= 0) {
      uploadOk.value = false
      uploadMessage.value = 'System Prompt 已达到 8000 字上限，请先精简后再上传'
      return
    }

    const body = text.slice(0, available)
    form.value.system_prompt = (current + header + body).slice(0, MAX_PROMPT_LENGTH)
    uploadOk.value = body.length >= text.length
    uploadMessage.value =
      body.length < text.length
        ? `「${file.name}」内容较长，已截断到 8000 字上限`
        : `已追加「${file.name}」共 ${body.length} 字`
  } catch (e) {
    uploadOk.value = false
    uploadMessage.value = e instanceof Error ? e.message : '文档解析失败'
  } finally {
    uploading.value = false
  }
}

async function loadTools() {
  try {
    const data = await api.get<Page<ToolDefinition>>('/api/mcp/tools?page_size=100')
    tools.value = data.items.filter((tool) => tool.enabled)
  } catch {
    // 工具列表失败不阻断表单
  }
}

async function loadAgentSkills() {
  if (!isEdit.value) return
  skillsLoading.value = true
  try {
    const [mine, mounted] = await Promise.all([
      api.get<Page<Skill>>('/api/skills?page_size=100'),
      api.get<AgentSkill[]>(`/api/agents/${rawId.value}/skills`),
    ])
    availableSkills.value = mine.items
    agentSkills.value = mounted.map((skill) => ({
      ...skill,
      params_text: JSON.stringify(skill.params ?? {}, null, 0),
    }))
  } catch {
    // Skill 列表失败不阻断基础表单
  } finally {
    skillsLoading.value = false
  }
}

function toggleTool(id: number) {
  const index = form.value.tool_ids.indexOf(id)
  if (index >= 0) form.value.tool_ids.splice(index, 1)
  else form.value.tool_ids.push(id)
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
    const data = await api.put<AgentSkill[]>(`/api/agents/${rawId.value}/skills`, payload)
    agentSkills.value = data.map((skill) => ({
      ...skill,
      params_text: JSON.stringify(skill.params ?? {}, null, 0),
    }))
    skillsMsg.value = 'Skills 已保存，运行时会按顺序注入'
  } catch (e) {
    error.value = errorMessage(e, 'Skills 保存失败')
  } finally {
    skillsSaving.value = false
  }
}

async function save() {
  error.value = ''
  successMsg.value = ''
  if (!form.value.name.trim()) {
    error.value = '请填写 Agent 名称'
    activeTab.value = 'basic'
    return
  }
  if (!form.value.model.trim()) {
    error.value = '请选择或填写模型'
    activeTab.value = 'model'
    return
  }

  saving.value = true
  try {
    if (!isEdit.value) {
      const created = await api.post<Agent>('/api/agents', {
        name: form.value.name,
        description: form.value.description || null,
        model: form.value.model,
        system_prompt: form.value.system_prompt,
        max_steps: form.value.max_steps,
        enabled: form.value.enabled,
        tool_ids: form.value.tool_ids,
      })
      successMsg.value = '新建成功'
      await router.replace(`/agents/${created.id}`)
      await loadAgentSkills()
    } else {
      await api.put<Agent>(`/api/agents/${rawId.value}`, {
        name: form.value.name,
        description: form.value.description || null,
        model: form.value.model,
        system_prompt: form.value.system_prompt,
        max_steps: form.value.max_steps,
        enabled: form.value.enabled,
      })
      const updated = await api.put<Agent>(`/api/agents/${rawId.value}/tools`, {
        tool_ids: form.value.tool_ids,
      })
      form.value.tool_ids = [...updated.tool_ids]
      successMsg.value = '保存成功'
    }
  } catch (e) {
    error.value = errorMessage(e, '保存失败')
  } finally {
    saving.value = false
  }
}

function onPublished() {
  publishOpen.value = false
  successMsg.value = '发布成功，已出现在 Agent Center'
}

onMounted(() => {
  const tab = route.query.tab
  if (typeof tab === 'string' && TABS.some((item) => item.key === tab)) {
    activeTab.value = tab as TabKey
  }
  loadAgent()
  loadTools()
  loadAgentSkills()
})
</script>

<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">
          {{ isEdit ? form.name || '编辑 Agent' : '新建 Agent' }}
        </h1>
      </div>
      <div class="head-actions">
        <router-link to="/agents" class="btn">返回列表</router-link>
        <router-link v-if="isEdit" :to="`/chat?agent=${rawId}`" class="btn">运行</router-link>
        <button v-if="isEdit" class="btn" type="button" @click="publishOpen = true">发布</button>
        <button class="btn-primary" type="button" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </div>
    </header>

    <p v-if="loading" class="muted">加载中…</p>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="successMsg" class="ok">{{ successMsg }}</p>

    <form v-if="!loading" class="editor" @submit.prevent="save">
      <nav class="tabs">
        <button
          v-for="tab in TABS"
          :key="tab.key"
          class="tab"
          :class="{ active: activeTab === tab.key }"
          type="button"
          @click="activeTab = tab.key"
        >
          {{ tab.label }}
        </button>
      </nav>

      <!-- 基础 -->
      <div v-show="activeTab === 'basic'" class="panel-body">
        <label class="row">
          <span>名称</span>
          <input v-model="form.name" type="text" maxlength="64" required />
        </label>

        <label class="row">
          <span>描述</span>
          <input v-model="form.description" type="text" maxlength="512" />
        </label>

        <div class="row">
          <div class="row-head">
            <span>System Prompt</span>
            <button
              class="btn btn-sm"
              type="button"
              :disabled="uploading"
              @click="fileInput?.click()"
            >
              {{ uploading ? '解析中…' : '上传文档' }}
            </button>
            <input
              ref="fileInput"
              type="file"
              :accept="DOCUMENT_ACCEPT"
              hidden
              @change="onDocumentSelected"
            />
          </div>
          <textarea v-model="form.system_prompt" rows="8" maxlength="8000"></textarea>
          <small v-if="uploadMessage" :class="uploadOk ? 'ok' : 'error'">{{ uploadMessage }}</small>
        </div>

        <label class="row">
          <span>最大执行步数</span>
          <input v-model.number="form.max_steps" type="number" min="1" max="20" />
          <small class="field-hint">1 ~ 20，默认 8；达到上限会提前结束并返回部分结果</small>
        </label>

        <div class="row enable-block">
          <label class="switch-row">
            <span>启用 Agent</span>
            <input v-model="form.enabled" type="checkbox" />
            <small class="field-hint">停用后不能发起新任务，配置和历史记录保留</small>
          </label>
        </div>
      </div>

      <!-- 模型 -->
      <div v-show="activeTab === 'model'" class="panel-body">
        <div class="row">
          <div class="row-head">
            <span>模型标识</span>
            <ModelSelector :model-value="form.model" @update:model-value="form.model = $event" />
          </div>
          <input v-model="form.model" type="text" maxlength="128" placeholder="例如：deepseek/deepseek-chat" required />
        </div>

        <router-link to="/settings/models" class="btn">管理模型 API</router-link>
      </div>

      <!-- Skills -->
      <div v-show="activeTab === 'skills'" class="panel-body">
        <p v-if="!isEdit" class="muted">保存 Agent 后可挂载 Skill。</p>
        <template v-else>
          <div class="skill-add">
            <select
              v-model.number="newSkillId"
              :class="{ placeholder: newSkillId == null }"
            >
              <option :value="null" disabled hidden>选择要挂载的 Skill</option>
              <option v-for="skill in selectableSkills" :key="skill.id" :value="skill.id">
                {{ skill.name }} · v{{ skill.version }}
              </option>
            </select>
            <button class="btn" type="button" @click="addSkill">挂载</button>
            <router-link to="/skills" class="btn">管理 Skills</router-link>
          </div>

          <p v-if="skillsLoading" class="muted">加载中…</p>

          <div v-if="agentSkills.length" class="skill-list">
            <div v-for="(skill, index) in agentSkills" :key="skill.skill_id" class="skill-item">
              <div class="skill-head">
                <strong>{{ index + 1 }}. {{ skill.name }}</strong>
                <code class="muted">{{ skill.slug }} · v{{ skill.version }}</code>
                <span class="badge" :class="skill.status">{{ statusLabel(skill.status) }}</span>
                <label class="inline-check">
                  <input v-model="skill.enabled" type="checkbox" />
                  启用
                </label>
                <span class="spacer"></span>
                <button
                  class="btn btn-sm"
                  type="button"
                  :disabled="index === 0"
                  @click="moveSkill(index, -1)"
                >
                  ↑
                </button>
                <button
                  class="btn btn-sm"
                  type="button"
                  :disabled="index === agentSkills.length - 1"
                  @click="moveSkill(index, 1)"
                >
                  ↓
                </button>
                <button class="btn btn-sm btn-danger" type="button" @click="removeSkill(index)">
                  移除
                </button>
              </div>

              <div v-if="skill.tools.length" class="skill-tools">
                <span class="muted">Skill 工具：</span>
                <span
                  v-for="tool in skill.tools"
                  :key="tool.tool_id"
                  class="tag"
                  :class="{ off: !tool.enabled }"
                >
                  {{ tool.qualified_name }}
                </span>
              </div>

              <label class="params">
                <span>参数覆盖（JSON，覆盖 Skill 默认值）</span>
                <input v-model="skill.params_text" type="text" placeholder='例如：{"tone":"正式"}' />
              </label>
            </div>
          </div>
          <p v-else-if="!skillsLoading" class="muted">尚未挂载 Skill。</p>

          <div class="skill-actions">
            <button class="btn-primary" type="button" :disabled="skillsSaving" @click="saveSkills">
              {{ skillsSaving ? '保存中…' : '保存 Skills' }}
            </button>
            <span v-if="skillsMsg" class="ok">{{ skillsMsg }}</span>
          </div>
        </template>
      </div>

      <!-- 工具 -->
      <div v-show="activeTab === 'tools'" class="panel-body">
        <div v-if="tools.length" class="tool-list">
          <label v-for="tool in tools" :key="tool.id" class="tool-item">
            <input
              type="checkbox"
              :checked="form.tool_ids.includes(tool.id)"
              :disabled="skillContributedTools.has(tool.qualified_name)"
              @change="toggleTool(tool.id)"
            />
            <span class="tool-name">
              <code>{{ tool.qualified_name }}</code>
              <span class="risk" :class="tool.risk_level.toLowerCase()">{{ riskLevelLabel(tool.risk_level) }}</span>
            </span>
            <span class="muted desc">{{ tool.description }}</span>
            <span v-if="skillContributedTools.has(tool.qualified_name)" class="skill-source">
              来自 Skill「{{ skillContributedTools.get(tool.qualified_name) }}」，自动加入可选工具
            </span>
          </label>
        </div>
        <p v-else class="muted">还没有工具，请先在 MCP Hub 注册 Server 并发现工具。</p>
      </div>

      <!-- 调试 -->
      <div v-show="activeTab === 'debug'" class="panel-body">
        <template v-if="isEdit">
          <RunPanel :agent-id="agentId" :agent-name="form.name" :default-steps="form.max_steps" />
        </template>
        <p v-else class="muted">保存 Agent 后可在此直接调试运行。</p>
      </div>
    </form>

    <PublishDialog
      v-if="publishOpen"
      :agent-id="agentId"
      :name="form.name"
      :description="form.description || null"
      @close="publishOpen = false"
      @published="onPublished"
    />
  </section>
</template>

<style scoped>
.head-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.editor {
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.editor .tabs {
  margin: 0;
  padding: 0 16px;
  background: var(--bg-panel);
}

.panel-body {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 860px;
}

.row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.row > span,
.row > label > span {
  font-size: 12.5px;
  color: var(--text-secondary);
}

.row-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.row-head > span {
  font-size: 12.5px;
  color: var(--text-secondary);
}

.row.two {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.row.two > label {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.switch-row {
  flex-direction: row !important;
  align-items: center;
  gap: 8px !important;
  flex-wrap: wrap;
}

.enable-block {
  border-top: 1px solid var(--border-color);
  padding-top: 16px;
}

.switch-row > span {
  font-size: 12.5px;
  color: var(--text-secondary);
}

.switch-row .field-hint {
  flex-basis: 100%;
}

.mono {
  font-family: var(--font-mono);
  font-size: 12px;
}

.skill-add {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.skill-add select {
  min-width: 240px;
}

.skill-add select.placeholder {
  color: var(--text-muted);
}

.skill-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.skill-item {
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: var(--bg-elevated);
}

.skill-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.skill-head code {
  font-size: 11.5px;
}

.inline-check {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  color: var(--text-muted);
}

.spacer {
  flex: 1;
}

.skill-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
}

.tag.off {
  color: var(--danger);
  text-decoration: line-through;
}

.params {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.params span {
  font-size: 11px;
  color: var(--text-muted);
}

.params input {
  font-family: var(--font-mono);
  font-size: 12px;
}

.skill-actions {
  display: flex;
  align-items: center;
  gap: 10px;
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
  border-radius: var(--radius-sm);
  font-size: 12.5px;
  background: var(--bg-elevated);
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
  font-size: 11.5px;
}

.skill-source {
  flex-basis: 100%;
  padding-left: 24px;
  font-size: 11px;
  color: var(--accent-hover);
}

.risk {
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 10.5px;
  background: var(--bg-panel);
  color: var(--text-secondary);
}

.risk.read_only {
  background: var(--success-soft);
  color: var(--success);
}

.risk.low_risk {
  background: var(--warn-soft);
  color: var(--warn);
}

.risk.write,
.risk.high_risk {
  background: var(--danger-soft);
  color: var(--danger);
}

@media (max-width: 768px) {
  .row.two {
    grid-template-columns: 1fr;
  }

  .page-header {
    flex-direction: column;
  }

  .head-actions {
    justify-content: flex-start;
  }
}
</style>

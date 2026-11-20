<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errorMessage, formatBytes, formatDateTime } from '../api/http'
import PublishDialog from '../components/PublishDialog.vue'
import RunPanel from '../components/RunPanel.vue'
import ToggleSwitch from '../components/ToggleSwitch.vue'
import { showNotice } from '../stores/ui'
import { DOCUMENT_ACCEPT, extractDocumentText } from '../utils/document-text'
import { loadDocxHtml } from '../utils/docx-preview'
import type { Agent, WorkspaceFile } from '../types/api'
import {
  riskLevelLabel,
  statusLabel,
  type AgentSkill,
  type Page,
  type Skill,
  type ToolDefinition,
} from '../types/skill'

type TabKey = 'basic' | 'skills' | 'tools' | 'files' | 'debug'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'basic', label: '基础' },
  { key: 'skills', label: 'Skills' },
  { key: 'tools', label: '工具' },
  { key: 'files', label: '文件管理' },
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

function tabLabel(key: TabKey, label: string): string {
  if (key === 'skills' && agentSkills.value.length) {
    return `${label} (${agentSkills.value.length})`
  }
  if (key === 'files' && workspaceFiles.value.length) {
    return `${label} (${workspaceFiles.value.length})`
  }
  return label
}

// Agent 专属工作区文件
const workspaceFiles = ref<WorkspaceFile[]>([])
const workspaceLoading = ref(false)
const workspaceUploading = ref(false)
const workspaceMsg = ref('')
const workspaceInput = ref<HTMLInputElement | null>(null)

async function loadWorkspaceFiles() {
  if (!isEdit.value) return
  workspaceLoading.value = true
  try {
    workspaceFiles.value = await api.get<WorkspaceFile[]>(`/api/agents/${rawId.value}/files`)
  } catch (e) {
    workspaceMsg.value = errorMessage(e, '文件列表加载失败')
  } finally {
    workspaceLoading.value = false
  }
}

async function onWorkspaceSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  if (!files.length) return

  workspaceUploading.value = true
  workspaceMsg.value = ''
  try {
    for (const file of files) {
      await api.upload<WorkspaceFile>(`/api/agents/${rawId.value}/files`, file)
    }
    workspaceMsg.value = `已上传 ${files.length} 个文件`
    await loadWorkspaceFiles()
  } catch (e) {
    workspaceMsg.value = errorMessage(e, '上传失败')
  } finally {
    workspaceUploading.value = false
  }
}

async function removeWorkspaceFile(name: string) {
  if (!window.confirm(`确定删除工作区文件「${name}」？`)) return
  workspaceMsg.value = ''
  try {
    await api.del(`/api/agents/${rawId.value}/files/${encodeURIComponent(name)}`)
    workspaceMsg.value = '已删除'
    await loadWorkspaceFiles()
  } catch (e) {
    workspaceMsg.value = errorMessage(e, '删除失败')
  }
}

function workspaceFileUrl(name: string): string {
  return `/api/agents/${rawId.value}/files/${encodeURIComponent(name)}`
}

// PDF / Word 预览
const previewFile = ref<WorkspaceFile | null>(null)
const previewHtml = ref('')
const previewLoading = ref(false)
const previewError = ref('')
const previewUrl = computed(() =>
  previewFile.value ? workspaceFileUrl(previewFile.value.name) : '',
)
const previewIsPdf = computed(() =>
  previewFile.value ? isPdf(previewFile.value.name) : false,
)
const previewIsWord = computed(() =>
  previewFile.value ? isWord(previewFile.value.name) : false,
)

function isPdf(name: string): boolean {
  return name.toLowerCase().endsWith('.pdf')
}

function isWord(name: string): boolean {
  return name.toLowerCase().endsWith('.docx')
}

async function openPreview(file: WorkspaceFile) {
  if (!isPdf(file.name) && !isWord(file.name)) return
  previewFile.value = file
  previewHtml.value = ''
  previewError.value = ''

  if (!isWord(file.name)) return
  previewLoading.value = true
  try {
    previewHtml.value = await loadDocxHtml(workspaceFileUrl(file.name))
  } catch (e) {
    previewError.value = errorMessage(e, 'Word 预览加载失败')
  } finally {
    previewLoading.value = false
  }
}

function closePreview() {
  previewFile.value = null
  previewHtml.value = ''
  previewError.value = ''
}

// 生成并下载 DOCX
const docOpen = ref(false)
const docTitle = ref('')
const docContent = ref('')
const docAuthor = ref('')
const docGenerating = ref(false)
const docMsg = ref('')

function openDocDialog() {
  docTitle.value = `${form.value.name || '示例'}文档`
  docAuthor.value = 'AgentHub'
  docContent.value = [
    '# 一级标题',
    '',
    '## 二级标题',
    '',
    '这是正文段落，用于验证首行缩进、字体与字号。',
    '',
    '- 列表项一',
    '- 列表项二',
  ].join('\n')
  docMsg.value = ''
  docOpen.value = true
}

function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1])
    } catch {
      return encoded[1]
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header)
  return plain ? plain[1] : null
}

async function generateAndDownloadDocx() {
  if (!docTitle.value.trim() || !docContent.value.trim()) {
    docMsg.value = '请填写文档标题和正文'
    return
  }

  docGenerating.value = true
  docMsg.value = ''
  try {
    const resp = await fetch(`/api/agents/${rawId.value}/documents`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: docTitle.value.trim(),
        content: docContent.value,
        author: docAuthor.value.trim(),
        format: 'docx',
      }),
    })
    if (!resp.ok) {
      let message = `HTTP ${resp.status}`
      try {
        const body = await resp.json()
        if (body?.message) message = body.message
      } catch {
        // 非 JSON 错误响应，保留状态码提示
      }
      throw new Error(message)
    }

    const blob = await resp.blob()
    const filename = filenameFromDisposition(resp.headers.get('Content-Disposition')) || 'document.docx'
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)

    docOpen.value = false
    workspaceMsg.value = `已生成并开始下载：${filename}`
    await loadWorkspaceFiles()
  } catch (e) {
    docMsg.value = errorMessage(e, '文档生成失败')
  } finally {
    docGenerating.value = false
  }
}


async function loadAgent() {
  if (!isEdit.value) return
  loading.value = true
  error.value = ''
  try {
    const agent = await api.get<Agent>(`/api/agents/${rawId.value}`)
    form.value = {
      name: agent.name,
      description: agent.description ?? '',
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

  saving.value = true
  try {
    if (!isEdit.value) {
      await api.post<Agent>('/api/agents', {
        name: form.value.name,
        description: form.value.description || null,
        system_prompt: form.value.system_prompt,
        max_steps: form.value.max_steps,
        enabled: form.value.enabled,
        tool_ids: form.value.tool_ids,
      })
    } else {
      await api.put<Agent>(`/api/agents/${rawId.value}`, {
        name: form.value.name,
        description: form.value.description || null,
        system_prompt: form.value.system_prompt,
        max_steps: form.value.max_steps,
        enabled: form.value.enabled,
      })
      const updated = await api.put<Agent>(`/api/agents/${rawId.value}/tools`, {
        tool_ids: form.value.tool_ids,
      })
      form.value.tool_ids = [...updated.tool_ids]
    }
    showNotice('保存成功')
    await router.push('/agents')
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
  loadWorkspaceFiles()
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
          {{ tabLabel(tab.key, tab.label) }}
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

        <p class="field-hint">
          模型不绑定在 Agent 上：Agent 只保存 Prompt、Skills 和工具，运行时在对话窗口选择模型。
        </p>

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
          <div class="switch-row">
            <span>启用 Agent</span>
            <ToggleSwitch v-model="form.enabled" />
            <small class="field-hint">停用后不能发起新任务，工作台不会再显示该 Agent，配置和历史记录保留</small>
          </div>
        </div>
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

      <!-- 文件管理 -->
      <div v-show="activeTab === 'files'" class="panel-body">
        <template v-if="isEdit">
          <div class="row-head">
            <span>Agent 专属工作区</span>
            <div class="workspace-ops">
              <button class="btn btn-sm" type="button" @click="openDocDialog">生成 DOCX</button>
              <button
                class="btn btn-sm"
                type="button"
                :disabled="workspaceUploading"
                @click="workspaceInput?.click()"
              >
                {{ workspaceUploading ? '上传中…' : '上传文件' }}
              </button>
              <input
                ref="workspaceInput"
                type="file"
                multiple
                hidden
                @change="onWorkspaceSelected"
              />
            </div>
          </div>
          <p class="field-hint">
            文件保存在服务器该 Agent 的专属目录中，支持上传、预览/下载与删除，单个文件不超过 20MB。
          </p>
          <p v-if="workspaceMsg" class="ok">{{ workspaceMsg }}</p>

          <p v-if="workspaceLoading" class="muted">加载中…</p>
          <div v-else-if="workspaceFiles.length" class="file-list">
            <div v-for="file in workspaceFiles" :key="file.name" class="file-item">
              <div class="file-main">
                <a
                  :href="workspaceFileUrl(file.name)"
                  target="_blank"
                  rel="noopener"
                  class="file-name"
                >
                  {{ file.name }}
                </a>
                <span class="muted">
                  {{ formatBytes(file.size) }} · {{ formatDateTime(file.updated_at) }}
                </span>
              </div>
              <div class="file-ops">
                <button
                  v-if="isPdf(file.name) || isWord(file.name)"
                  class="btn btn-sm"
                  type="button"
                  @click="openPreview(file)"
                >
                  预览
                </button>
                <button
                  class="btn btn-sm btn-danger"
                  type="button"
                  @click="removeWorkspaceFile(file.name)"
                >
                  删除
                </button>
              </div>
            </div>
          </div>
          <p v-else class="muted">还没有文件，点击「上传文件」添加。</p>
        </template>
        <p v-else class="muted">保存 Agent 后会自动创建专属工作区，可在此上传文件。</p>
      </div>

      <!-- 调试 -->
      <div v-show="activeTab === 'debug'" class="panel-body">
        <template v-if="isEdit">
          <RunPanel :agent-id="agentId" :agent-name="form.name" :default-steps="form.max_steps" />
        </template>
        <p v-else class="muted">保存 Agent 后可在此直接调试运行。</p>
      </div>
    </form>

    <div v-if="previewFile" class="pdf-overlay" @click.self="closePreview">
      <div class="pdf-modal">
        <header class="pdf-head">
          <span class="pdf-title">{{ previewFile.name }}</span>
          <div class="pdf-ops">
            <a :href="previewUrl" target="_blank" rel="noopener" class="btn btn-sm">下载</a>
            <button class="btn btn-sm" type="button" @click="closePreview">关闭</button>
          </div>
        </header>
        <iframe v-if="previewIsPdf" :src="previewUrl" title="PDF 预览"></iframe>

        <div v-else-if="previewIsWord" class="preview-docx">
          <p v-if="previewLoading" class="muted preview-tip">Word 预览加载中…</p>
          <p v-else-if="previewError" class="muted preview-tip">
            {{ previewError }}，请下载后查看。
          </p>
          <div v-else class="docx-content" v-html="previewHtml"></div>
        </div>
      </div>
    </div>

    <div v-if="docOpen" class="pdf-overlay" @click.self="docOpen = false">
      <div class="doc-modal">
        <header class="pdf-head">
          <span class="pdf-title">生成 Word 文档</span>
          <button class="btn btn-sm" type="button" @click="docOpen = false">关闭</button>
        </header>
        <div class="doc-body">
          <label class="doc-field">
            <span>标题</span>
            <input v-model="docTitle" type="text" maxlength="200" />
          </label>
          <label class="doc-field">
            <span>作者</span>
            <input v-model="docAuthor" type="text" maxlength="100" />
          </label>
          <label class="doc-field">
            <span>正文（支持 # / ## / - 结构）</span>
            <textarea v-model="docContent" rows="10"></textarea>
          </label>
          <p v-if="docMsg" class="error">{{ docMsg }}</p>
          <div class="doc-actions">
            <button
              class="btn-primary"
              type="button"
              :disabled="docGenerating"
              @click="generateAndDownloadDocx"
            >
              {{ docGenerating ? '生成中…' : '生成并下载 DOCX' }}
            </button>
          </div>
        </div>
      </div>
    </div>

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

.file-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.file-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-elevated);
}

.file-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
}

.file-ops {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.workspace-ops {
  display: flex;
  align-items: center;
  gap: 8px;
}

.doc-modal {
  width: min(720px, 92vw);
  max-height: 88vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  overflow: hidden;
  box-shadow: var(--shadow-pop);
}

.doc-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  overflow-y: auto;
}

.doc-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12.5px;
  color: var(--text-secondary);
}

.doc-field input,
.doc-field textarea {
  padding: 8px 10px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-elevated);
  color: var(--text-main);
  font-family: inherit;
  font-size: 13px;
}

.doc-field textarea {
  min-height: 180px;
  resize: vertical;
  font-family: 'JetBrains Mono', Consolas, Monaco, monospace;
  line-height: 1.6;
}

.doc-actions {
  display: flex;
  justify-content: flex-end;
}

.pdf-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
  background: rgba(0, 0, 0, 0.55);
}

.pdf-modal {
  width: min(1000px, 92vw);
  height: min(820px, 88vh);
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  overflow: hidden;
  box-shadow: var(--shadow-pop);
}

.pdf-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-color);
}

.pdf-title {
  font-size: 12.5px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pdf-ops {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.pdf-modal iframe {
  flex: 1;
  width: 100%;
  border: none;
  background: #fff;
}

.preview-docx {
  flex: 1;
  overflow-y: auto;
  background: #fff;
}

.preview-tip {
  padding: 24px;
  text-align: center;
}

.docx-content {
  padding: 28px 36px;
  color: #1f2937;
  font-family: '宋体', 'Songti SC', serif;
  font-size: 14px;
  line-height: 1.8;
}

.docx-content :deep(h1) {
  margin: 18px 0 8px;
  font-family: '黑体', 'Heiti SC', sans-serif;
  font-size: 18px;
  font-weight: 700;
}

.docx-content :deep(h2) {
  margin: 16px 0 6px;
  font-size: 16px;
  font-weight: 700;
}

.docx-content :deep(h3) {
  margin: 14px 0 6px;
  font-size: 15px;
  font-weight: 700;
}

.docx-content :deep(p) {
  margin: 8px 0;
  text-indent: 2em;
}

.docx-content :deep(ul),
.docx-content :deep(ol) {
  margin: 8px 0;
  padding-left: 28px;
}

.docx-content :deep(li) {
  margin: 4px 0;
}

.docx-content :deep(table) {
  width: 100%;
  margin: 12px 0;
  border-collapse: collapse;
}

.docx-content :deep(th),
.docx-content :deep(td) {
  padding: 6px 8px;
  border: 1px solid #d1d5db;
  text-align: left;
}

.file-name {
  color: var(--accent-hover);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-name:hover {
  text-decoration: underline;
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

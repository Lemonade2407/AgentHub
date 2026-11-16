<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  SKILL_CATEGORIES,
  parametersFromSchema,
  renderInstructions,
  statusLabel,
  type Page,
  type Skill,
  type SkillParameterSpec,
  type ToolDefinition,
} from '../types/skill'

interface ToolDraft {
  tool_id: number
  required: boolean
}

const route = useRoute()
const router = useRouter()

const rawId = computed(() => {
  const value = route.params.id
  return Array.isArray(value) ? value[0] : value
})
const isNew = computed(() => rawId.value === 'new')
const skillId = computed(() => Number(rawId.value))

const form = reactive({
  name: '',
  slug: '',
  summary: '',
  category: 'general',
  icon: '',
  version: '1.0.0',
  instructions: '',
  tagsText: '',
  schemaText: '{\n  "type": "object",\n  "properties": {}\n}',
})

const tools = ref<ToolDefinition[]>([])
const toolDrafts = ref<ToolDraft[]>([])
const skill = ref<Skill | null>(null)
const owned = ref(true)

const loading = ref(false)
const saving = ref(false)
const busy = ref(false)
const error = ref('')
const message = ref('')

const previewValues = reactive<Record<string, string>>({})

const parsedSchema = computed<{ value: Record<string, unknown> | null; error: string }>(() => {
  try {
    const value = JSON.parse(form.schemaText || '{}')
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return { value: null, error: 'input_schema 必须是 JSON 对象' }
    }
    return { value: value as Record<string, unknown>, error: '' }
  } catch (e) {
    return { value: null, error: e instanceof Error ? e.message : 'JSON 格式错误' }
  }
})

const parameters = computed(() => parametersFromSchema(parsedSchema.value.value))

const previewText = computed(() => {
  const values: Record<string, unknown> = {}
  for (const param of parameters.value) {
    values[param.name] =
      param.name in previewValues ? previewValues[param.name] : param.default ?? ''
  }
  return renderInstructions(form.instructions, values)
})

const selectedTools = computed(() => {
  const byId = new Map(tools.value.map((tool) => [tool.id, tool]))
  return toolDrafts.value
    .map((draft) => ({ draft, tool: byId.get(draft.tool_id) }))
    .filter((item): item is { draft: ToolDraft; tool: ToolDefinition } => Boolean(item.tool))
})

function failMessage(resp: Response): Promise<string> {
  return resp
    .json()
    .catch(() => null)
    .then((body) => body?.message ?? `HTTP ${resp.status}`)
}

async function loadTools() {
  try {
    const resp = await fetch('/api/mcp/tools?page_size=100')
    if (!resp.ok) return
    const data: Page<ToolDefinition> = await resp.json()
    tools.value = data.items
  } catch {
    // 工具列表失败不阻断编辑器
  }
}

async function loadSkill() {
  if (isNew.value) return
  loading.value = true
  error.value = ''
  try {
    const resp = await fetch(`/api/skills/${skillId.value}`)
    if (!resp.ok) throw new Error(await failMessage(resp))
    const data: Skill = await resp.json()
    skill.value = data
    owned.value = data.owned
    form.name = data.name
    form.slug = data.slug
    form.summary = data.summary
    form.category = data.category
    form.icon = data.icon ?? ''
    form.version = data.version
    form.instructions = data.instructions
    form.tagsText = data.tags.join(', ')
    form.schemaText = JSON.stringify(data.input_schema ?? {}, null, 2)
    toolDrafts.value = data.tools.map((tool) => ({
      tool_id: tool.tool_id,
      required: tool.required,
    }))
    for (const param of parametersFromSchema(data.input_schema)) {
      if (param.default != null) previewValues[param.name] = String(param.default)
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function isSelected(toolId: number): boolean {
  return toolDrafts.value.some((draft) => draft.tool_id === toolId)
}

function toggleTool(tool: ToolDefinition) {
  if (!owned.value) return
  const index = toolDrafts.value.findIndex((draft) => draft.tool_id === tool.id)
  if (index >= 0) toolDrafts.value.splice(index, 1)
  else toolDrafts.value.push({ tool_id: tool.id, required: true })
}

function setRequired(toolId: number, required: boolean) {
  const draft = toolDrafts.value.find((item) => item.tool_id === toolId)
  if (draft) draft.required = required
}

function onParamInput(name: string, event: Event) {
  previewValues[name] = (event.target as HTMLInputElement).value
}

function onParamToggle(name: string, event: Event) {
  previewValues[name] = (event.target as HTMLInputElement).checked ? 'true' : 'false'
}

function paramValue(param: SkillParameterSpec): string {
  if (param.name in previewValues) return previewValues[param.name]
  return param.default == null ? '' : String(param.default)
}

function paramChecked(param: SkillParameterSpec): boolean {
  const value = param.name in previewValues ? previewValues[param.name] : param.default
  return value === true || value === 'true'
}

function onRequiredChange(toolId: number, event: Event) {
  setRequired(toolId, (event.target as HTMLInputElement).checked)
}

function buildPayload() {
  return {
    name: form.name.trim(),
    slug: form.slug.trim() || undefined,
    summary: form.summary.trim(),
    category: form.category,
    icon: form.icon.trim() || null,
    version: form.version.trim() || '1.0.0',
    instructions: form.instructions,
    input_schema: parsedSchema.value.value ?? {},
    tags: form.tagsText
      .split(',')
      .map((tag) => tag.trim())
      .filter(Boolean),
    tools: toolDrafts.value,
  }
}

async function save() {
  error.value = ''
  message.value = ''
  if (!form.name.trim()) {
    error.value = '请填写 Skill 名称'
    return
  }
  if (parsedSchema.value.error) {
    error.value = `input_schema 不合法：${parsedSchema.value.error}`
    return
  }

  saving.value = true
  try {
    const resp = await fetch(isNew.value ? '/api/skills' : `/api/skills/${skillId.value}`, {
      method: isNew.value ? 'POST' : 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildPayload()),
    })
    if (!resp.ok) throw new Error(await failMessage(resp))
    const saved: Skill = await resp.json()
    skill.value = saved
    owned.value = saved.owned
    message.value = isNew.value ? '创建成功' : '保存成功'
    if (isNew.value) router.replace(`/skills/${saved.id}`)
    else await loadSkill()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

async function action(path: string, method: string, success: string) {
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    const resp = await fetch(path, { method })
    if (!resp.ok) throw new Error(await failMessage(resp))
    message.value = success
    await loadSkill()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

function publish() {
  action(`/api/skills/${skillId.value}/publish`, 'POST', '已公开，其他账号可在广场看到')
}

function archive() {
  action(`/api/skills/${skillId.value}/archive`, 'POST', '已下架')
}

async function install() {
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    const resp = await fetch(`/api/skills/${skillId.value}/install`, { method: 'POST' })
    if (!resp.ok) throw new Error(await failMessage(resp))
    const copy: Skill = await resp.json()
    router.push(`/skills/${copy.id}`)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

async function remove() {
  if (!window.confirm(`确定删除「${form.name}」？被 Agent 挂载时无法删除。`)) return
  busy.value = true
  error.value = ''
  try {
    const resp = await fetch(`/api/skills/${skillId.value}`, { method: 'DELETE' })
    if (!resp.ok) throw new Error(await failMessage(resp))
    router.push('/skills')
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    busy.value = false
  }
}

async function exportSkill() {
  error.value = ''
  try {
    const resp = await fetch(`/api/skills/${skillId.value}/export`)
    if (!resp.ok) throw new Error(await failMessage(resp))
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${form.slug || 'skill'}.skill.json`
    link.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

onMounted(async () => {
  await Promise.all([loadTools(), loadSkill()])
})
</script>

<template>
  <section class="page">
    <div class="header">
      <div>
        <h1>{{ isNew ? '新建 Skill' : form.name || 'Skill 编辑器' }}</h1>
        <p v-if="skill" class="muted">
          {{ skill.slug }} · v{{ skill.version }} ·
          <span class="badge" :class="skill.status">{{ statusLabel(skill.status) }}</span>
          · 作者 {{ skill.owner_display_name || '匿名' }}
        </p>
      </div>
      <div class="header-actions">
        <button class="btn" @click="router.push('/skills')">返回列表</button>
        <template v-if="!isNew && owned">
          <button class="btn" :disabled="busy" @click="exportSkill">导出 JSON</button>
          <button v-if="skill?.status !== 'published'" class="btn" :disabled="busy" @click="publish">
            公开
          </button>
          <button v-else class="btn" :disabled="busy" @click="archive">下架</button>
          <button class="btn danger" :disabled="busy" @click="remove">删除</button>
        </template>
        <button v-if="!isNew && !owned" class="btn-primary" :disabled="busy" @click="install">
          安装到我的 Skills
        </button>
      </div>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="message" class="ok">{{ message }}</p>
    <p v-if="loading" class="muted">加载中…</p>
    <p v-if="!isNew && !owned" class="notice">
      这是其他用户的公开 Skill，当前为只读预览。安装后可自由修改与挂载。
    </p>

    <div v-if="!loading" class="layout">
      <form class="editor" @submit.prevent="save">
        <fieldset :disabled="!owned">
          <div class="row two">
            <label>
              <span>名称 *</span>
              <input v-model="form.name" type="text" maxlength="64" required />
            </label>
            <label>
              <span>Slug</span>
              <input v-model="form.slug" type="text" maxlength="80" :placeholder="isNew ? '留空自动生成' : ''" />
            </label>
          </div>

          <div class="row two">
            <label>
              <span>分类</span>
              <select v-model="form.category">
                <option v-for="item in SKILL_CATEGORIES" :key="item.value" :value="item.value">
                  {{ item.label }}
                </option>
              </select>
            </label>
            <label>
              <span>版本</span>
              <input v-model="form.version" type="text" maxlength="16" />
            </label>
          </div>

          <div class="row two">
            <label>
              <span>图标名</span>
              <input v-model="form.icon" type="text" maxlength="64" placeholder="可选，前端图标名" />
            </label>
            <label>
              <span>标签</span>
              <input v-model="form.tagsText" type="text" placeholder="用逗号分隔，如：周报, 总结" />
            </label>
          </div>

          <label class="row">
            <span>简介</span>
            <input v-model="form.summary" type="text" maxlength="512" />
          </label>

          <label class="row">
            <span v-pre>指令片段（instructions，支持 {{param}} 占位）</span>
            <textarea
              v-model="form.instructions"
              rows="8"
              maxlength="20000"
              :placeholder="'例如：请用 {{tone}} 的语气，把本周 Git 提交整理成周报。'"
            ></textarea>
          </label>

          <label class="row">
            <span>参数契约 input_schema（JSON Schema 子集）</span>
            <textarea v-model="form.schemaText" rows="8" spellcheck="false"></textarea>
            <small v-if="parsedSchema.error" class="error">{{ parsedSchema.error }}</small>
            <small v-else class="muted">
              示例：{"type":"object","properties":{"tone":{"type":"string","default":"正式"}}}
            </small>
          </label>

          <div class="row">
            <span>绑定工具（Skill 挂载到 Agent 后自动进入候选工具池）</span>
            <div v-if="tools.length" class="tool-list">
              <div v-for="tool in tools" :key="tool.id" class="tool-item">
                <label class="tool-check">
                  <input
                    type="checkbox"
                    :checked="isSelected(tool.id)"
                    :disabled="!owned"
                    @change="toggleTool(tool)"
                  />
                  <code>{{ tool.qualified_name }}</code>
                  <span class="risk" :class="tool.risk_level.toLowerCase()">{{ tool.risk_level }}</span>
                  <span v-if="!tool.enabled" class="risk write">已禁用</span>
                </label>
                <label v-if="isSelected(tool.id)" class="required">
                  <input
                    type="checkbox"
                    :checked="toolDrafts.find((item) => item.tool_id === tool.id)?.required"
                    :disabled="!owned"
                    @change="onRequiredChange(tool.id, $event)"
                  />
                  必填（缺失时拒绝运行）
                </label>
                <span class="muted desc">{{ tool.description }}</span>
              </div>
            </div>
            <p v-else class="muted">暂无工具，请先在 MCP Center 完成 Server 发现。</p>
          </div>
        </fieldset>

        <div v-if="owned" class="actions">
          <button class="btn-primary" type="submit" :disabled="saving || busy">
            {{ saving ? '保存中…' : isNew ? '创建' : '保存' }}
          </button>
        </div>
      </form>

      <aside class="preview">
        <h2>预览</h2>

        <section class="preview-block">
          <h3>参数表单</h3>
          <p v-if="!parameters.length" class="muted">未声明参数。</p>
          <div v-for="param in parameters" :key="param.name" class="param-row">
            <label>
              <span>
                {{ param.name }}
                <em v-if="param.required" class="required-mark">*</em>
                <small class="muted">{{ param.type }}</small>
              </span>
              <input
                v-if="param.type !== 'boolean'"
                :value="paramValue(param)"
                @input="onParamInput(param.name, $event)"
              />
              <input
                v-else
                type="checkbox"
                :checked="paramChecked(param)"
                @change="onParamToggle(param.name, $event)"
              />
            </label>
            <small v-if="param.description" class="muted">{{ param.description }}</small>
          </div>
        </section>

        <section class="preview-block">
          <h3>注入片段</h3>
          <pre v-if="previewText.trim()" class="prompt">{{ previewText }}</pre>
          <p v-else class="muted">填写 instructions 后可预览渲染结果。</p>
        </section>

        <section class="preview-block">
          <h3>最终加入 System Prompt</h3>
          <pre v-if="form.instructions.trim()" class="prompt">## Skill: {{ form.name || '未命名' }} (v{{ form.version }})

{{ previewText }}</pre>
          <p v-else class="muted">纯工具型 Skill 不占用 Prompt 预算。</p>
        </section>

        <section class="preview-block">
          <h3>本次 Skill 工具</h3>
          <p v-if="!selectedTools.length" class="muted">未绑定工具。</p>
          <ul v-else class="selected-tools">
            <li v-for="item in selectedTools" :key="item.tool.id">
              <code>{{ item.tool.qualified_name }}</code>
              <span v-if="item.draft.required" class="badge published">必填</span>
              <span v-if="!item.tool.enabled" class="badge archived">不可用</span>
            </li>
          </ul>
        </section>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 12px;
}

.header h1 {
  margin: 0 0 4px;
}

.header p {
  margin: 0;
  font-size: 13px;
}

.header-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.layout {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(320px, 1fr);
  gap: 18px;
  align-items: start;
}

@media (max-width: 1024px) {
  .layout {
    grid-template-columns: 1fr;
  }
}

.editor,
.preview {
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 18px;
}

fieldset {
  border: none;
  padding: 0;
  margin: 0;
  min-width: 0;
}

.row {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 14px;
}

.row.two {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.row > label {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

span {
  font-size: 13px;
  font-weight: 600;
}

input[type='text'],
select,
textarea {
  padding: 8px 10px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-family: inherit;
  font-size: 13px;
  width: 100%;
  box-sizing: border-box;
}

textarea {
  resize: vertical;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.tool-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 340px;
  overflow-y: auto;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 8px;
}

.tool-item {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 6px;
  border-radius: 6px;
}

.tool-item:hover {
  background: var(--surface-muted);
}

.tool-check {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.required {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-muted);
}

.desc {
  flex-basis: 100%;
  font-size: 12px;
  padding-left: 24px;
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

.risk.write,
.risk.high_risk {
  background: #ffebe9;
  color: #cf222e;
}

.actions {
  display: flex;
  gap: 10px;
}

.preview h2 {
  margin: 0 0 12px;
  font-size: 16px;
}

.preview-block {
  margin-bottom: 18px;
}

.preview-block h3 {
  margin: 0 0 8px;
  font-size: 13px;
  color: var(--text-muted);
  font-weight: 600;
}

.param-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 8px;
}

.param-row label {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.param-row span {
  display: flex;
  align-items: center;
  gap: 6px;
}

.param-row small {
  font-size: 11px;
}

.required-mark {
  color: #cf222e;
  font-style: normal;
}

.prompt {
  margin: 0;
  background: var(--surface-muted);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 260px;
  overflow: auto;
}

.selected-tools {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
}

.selected-tools li {
  margin-bottom: 4px;
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

.btn {
  padding: 6px 12px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: #fff;
  cursor: pointer;
  font-size: 13px;
}

.btn.danger {
  color: #cf222e;
  border-color: #ffcecb;
}

.btn-primary {
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  background: #1a7f37;
  color: #fff;
  cursor: pointer;
  font-size: 13px;
}

.btn:disabled,
.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.notice {
  background: #ddf4ff;
  border: 1px solid #b6e3ff;
  color: #0969da;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
}

.error {
  color: #d1242f;
}

.ok {
  color: #1a7f37;
}

.muted {
  color: var(--text-muted);
}
</style>

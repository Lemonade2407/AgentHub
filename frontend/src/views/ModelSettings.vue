<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage, formatDateTime, isRouteMissing } from '../api/http'
import { DEMO_MODEL_APIS } from '../data/demo'
import {
  PROVIDERS,
  providerLabel,
  type ModelApi,
  type ModelApiModel,
  type ModelApiTestResult,
  type Page,
} from '../types/api'

interface ModelDraft {
  id?: number
  model_key: string
  display_name: string
}

interface ApiForm {
  name: string
  provider: string
  base_url: string
  api_key: string
  is_default: boolean
  enabled: boolean
  models: ModelDraft[]
}

function emptyForm(): ApiForm {
  return {
    name: '',
    provider: 'deepseek',
    base_url: 'https://api.deepseek.com/v1',
    api_key: '',
    is_default: false,
    enabled: true,
    models: [],
  }
}

const items = ref<ModelApi[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
const demoMode = ref(false)

const drawerOpen = ref(false)
const editingId = ref<number | null>(null)
const form = ref<ApiForm>(emptyForm())
const modelDraft = ref('')
const saving = ref(false)
const drawerError = ref('')
const testing = ref(false)
const testText = ref('')

const busyId = ref<number | null>(null)

const drawerTitle = computed(() => (editingId.value == null ? '添加模型 API' : '编辑模型 API'))

function modelsOf(item: ModelApi): ModelApiModel[] {
  return item.models ?? item.model_api_models ?? []
}

function maskedKey(item: ModelApi): string {
  return item.api_key_hint ? `****${item.api_key_hint}` : '未设置'
}

function testBadge(item: ModelApi): { label: string; cls: string } {
  if (item.last_test_ok === true) return { label: '测试通过', cls: 'on' }
  if (item.last_test_ok === false) return { label: '测试失败', cls: 'error' }
  return { label: '未测试', cls: 'off' }
}

function flash(message: string) {
  notice.value = message
  window.setTimeout(() => {
    if (notice.value === message) notice.value = ''
  }, 3200)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const raw = await api.get<ModelApi[] | Page<ModelApi>>('/api/model-apis')
    items.value = Array.isArray(raw) ? raw : raw.items
    demoMode.value = false
  } catch (e) {
    if (isRouteMissing(e)) {
      items.value = DEMO_MODEL_APIS
      demoMode.value = true
    } else {
      error.value = errorMessage(e, '模型 API 列表加载失败')
    }
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  drawerError.value = ''
  testText.value = ''
  drawerOpen.value = true
}

function openEdit(item: ModelApi) {
  editingId.value = item.id
  form.value = {
    name: item.name,
    provider: item.provider,
    base_url: item.base_url,
    api_key: '',
    is_default: item.is_default,
    enabled: item.enabled,
    models: modelsOf(item).map((model) => ({
      id: model.id,
      model_key: model.model_key,
      display_name: model.display_name || model.model_key,
    })),
  }
  drawerError.value = ''
  testText.value = ''
  drawerOpen.value = true
}

function addModel() {
  const key = modelDraft.value.trim()
  if (!key) return
  if (form.value.models.some((model) => model.model_key === key)) {
    modelDraft.value = ''
    return
  }
  form.value.models.push({ model_key: key, display_name: key })
  modelDraft.value = ''
}

function removeModel(index: number) {
  form.value.models.splice(index, 1)
}

function applyTestModels(models: string[]) {
  for (const key of models) {
    if (!form.value.models.some((model) => model.model_key === key)) {
      form.value.models.push({ model_key: key, display_name: key })
    }
  }
}

async function runTest(item: ModelApi) {
  if (demoMode.value) {
    flash('演示数据：后端测试接口未就绪（D：WP-1.3）')
    return
  }
  busyId.value = item.id
  error.value = ''
  try {
    const result = await api.post<ModelApiTestResult>(`/api/model-apis/${item.id}/test`)
    if (result.ok) {
      item.last_test_ok = true
      item.last_test_at = new Date().toISOString()
      item.last_error = null
      flash(
        `「${item.name}」测试通过${result.latency_ms != null ? ` · ${result.latency_ms}ms` : ''}${
          result.models?.length ? ` · ${result.models.length} 个模型` : ''
        }`,
      )
    } else {
      item.last_test_ok = false
      item.last_error = result.error ?? '测试失败'
      error.value = `「${item.name}」测试失败：${result.error ?? '未知错误'}`
    }
  } catch (e) {
    error.value = `「${item.name}」测试失败：${errorMessage(e)}`
  } finally {
    busyId.value = null
  }
}

async function testInDrawer() {
  if (editingId.value == null) {
    drawerError.value = '请先保存后再测试连接'
    return
  }
  if (demoMode.value) {
    testText.value = '演示数据：后端测试接口未就绪'
    return
  }
  testing.value = true
  testText.value = ''
  try {
    const result = await api.post<ModelApiTestResult>(
      `/api/model-apis/${editingId.value}/test`,
    )
    if (result.ok) {
      testText.value = `连接成功${result.latency_ms != null ? ` · ${result.latency_ms}ms` : ''}${
        result.models?.length ? ` · 可用模型 ${result.models.length} 个` : ''
      }`
      if (result.models?.length) applyTestModels(result.models)
    } else {
      testText.value = `连接失败：${result.error ?? '未知错误'}`
    }
  } catch (e) {
    testText.value = `连接失败：${errorMessage(e)}`
  } finally {
    testing.value = false
  }
}

async function save() {
  drawerError.value = ''
  if (!form.value.name.trim()) {
    drawerError.value = '请填写名称'
    return
  }
  if (!form.value.base_url.trim()) {
    drawerError.value = '请填写 Base URL'
    return
  }
  if (editingId.value == null && !form.value.api_key.trim() && !demoMode.value) {
    drawerError.value = '新建时 API Key 必填'
    return
  }

  saving.value = true
  try {
    if (demoMode.value) {
      applyDemoSave()
      drawerOpen.value = false
      return
    }

    if (editingId.value == null) {
      const created = await api.post<ModelApi>('/api/model-apis', {
        name: form.value.name.trim(),
        provider: form.value.provider,
        base_url: form.value.base_url.trim(),
        api_key: form.value.api_key.trim(),
        is_default: form.value.is_default,
        enabled: form.value.enabled,
      })
      for (const model of form.value.models) {
        await api.post(`/api/model-apis/${created.id}/models`, {
          model_key: model.model_key,
          display_name: model.display_name || model.model_key,
        })
      }
      flash(`已添加「${created.name}」`)
    } else {
      const payload: Record<string, unknown> = {
        name: form.value.name.trim(),
        provider: form.value.provider,
        base_url: form.value.base_url.trim(),
        is_default: form.value.is_default,
        enabled: form.value.enabled,
      }
      if (form.value.api_key.trim()) payload.api_key = form.value.api_key.trim()
      await api.put(`/api/model-apis/${editingId.value}`, payload)

      const original = items.value.find((item) => item.id === editingId.value)
      const originalModels = original ? modelsOf(original) : []
      const keptIds = new Set(form.value.models.map((model) => model.id).filter(Boolean))
      for (const model of originalModels) {
        if (model.id != null && !keptIds.has(model.id)) {
          await api.del(`/api/model-apis/${editingId.value}/models/${model.id}`)
        }
      }
      for (const model of form.value.models) {
        if (model.id == null) {
          await api.post(`/api/model-apis/${editingId.value}/models`, {
            model_key: model.model_key,
            display_name: model.display_name || model.model_key,
          })
        }
      }
      flash('保存成功')
    }

    drawerOpen.value = false
    await load()
  } catch (e) {
    drawerError.value = errorMessage(e, '保存失败')
  } finally {
    saving.value = false
  }
}

function applyDemoSave() {
  const models: ModelDraft[] = form.value.models.map((model, index) => ({
    ...model,
    id: model.id ?? Date.now() + index,
  }))
  if (editingId.value == null) {
    items.value = [
      ...items.value,
      {
        id: Date.now(),
        name: form.value.name.trim(),
        provider: form.value.provider,
        base_url: form.value.base_url.trim(),
        api_key_hint: form.value.api_key.slice(-4) || null,
        is_default: form.value.is_default,
        enabled: form.value.enabled,
        last_test_at: null,
        last_test_ok: null,
        last_error: null,
        models: models.map((model) => ({
          id: model.id,
          model_key: model.model_key,
          display_name: model.display_name,
          enabled: true,
        })),
      },
    ]
    flash('演示数据已添加（刷新页面后重置）')
  } else {
    const target = items.value.find((item) => item.id === editingId.value)
    if (target) {
      target.name = form.value.name.trim()
      target.provider = form.value.provider
      target.base_url = form.value.base_url.trim()
      target.is_default = form.value.is_default
      target.enabled = form.value.enabled
      target.models = models.map((model) => ({
        id: model.id,
        model_key: model.model_key,
        display_name: model.display_name,
        enabled: true,
      }))
    }
    flash('演示数据已更新（刷新页面后重置）')
  }
}

async function remove(item: ModelApi) {
  if (!window.confirm(`确定删除「${item.name}」？被 Agent 引用时会被拒绝。`)) return
  if (demoMode.value) {
    items.value = items.value.filter((entry) => entry.id !== item.id)
    flash('演示数据已删除（刷新页面后重置）')
    return
  }
  busyId.value = item.id
  error.value = ''
  try {
    await api.del(`/api/model-apis/${item.id}`)
    flash(`已删除「${item.name}」`)
    await load()
  } catch (e) {
    error.value = errorMessage(e, '删除失败')
  } finally {
    busyId.value = null
  }
}

onMounted(load)
</script>

<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">模型 API</h1>
      </div>
      <button class="btn-primary" type="button" @click="openCreate">添加模型 API</button>
    </header>

    <div v-if="demoMode" class="demo-banner">
      <span class="demo-badge">演示数据</span>
      后端模型 API 接口（D：WP-1.2 / WP-1.3）尚未就绪，本页使用本地演示数据，保存仅在本页生效。
    </div>

    <p v-if="error" class="error-box">{{ error }}</p>
    <p v-if="notice" class="ok notice">{{ notice }}</p>
    <p v-if="loading" class="muted">加载中…</p>

    <table v-if="!loading && items.length" class="table">
      <thead>
        <tr>
          <th>名称</th>
          <th>Provider</th>
          <th>Base URL</th>
          <th>Key</th>
          <th>模型</th>
          <th>上次测试</th>
          <th>默认</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in items" :key="item.id">
          <td>
            <div class="name-cell">
              <strong>{{ item.name }}</strong>
              <span v-if="!item.enabled" class="badge off">已禁用</span>
            </div>
          </td>
          <td>{{ providerLabel(item.provider) }}</td>
          <td class="mono">{{ item.base_url }}</td>
          <td class="mono">{{ maskedKey(item) }}</td>
          <td>{{ modelsOf(item).length }}</td>
          <td>
            <span class="badge" :class="testBadge(item).cls">{{ testBadge(item).label }}</span>
            <span v-if="item.last_test_at" class="muted test-time">
              {{ formatDateTime(item.last_test_at) }}
            </span>
          </td>
          <td>
            <span v-if="item.is_default" class="badge on">默认</span>
            <span v-else class="muted">-</span>
          </td>
          <td class="ops">
            <button class="btn btn-sm" type="button" :disabled="busyId === item.id" @click="runTest(item)">
              {{ busyId === item.id ? '测试中…' : '测试连接' }}
            </button>
            <button class="btn btn-sm" type="button" @click="openEdit(item)">编辑</button>
            <button class="btn btn-sm btn-danger" type="button" :disabled="busyId === item.id" @click="remove(item)">
              删除
            </button>
          </td>
        </tr>
      </tbody>
    </table>

    <p v-else-if="!loading" class="empty">
      还没有模型 API。添加一条后，Agent 编辑器即可选择其下的模型。
    </p>

    <!-- 右侧抽屉 -->
    <div v-if="drawerOpen" class="drawer-mask" @click.self="drawerOpen = false">
      <form class="drawer" @submit.prevent="save">
        <header class="drawer-head">
          <h2>{{ drawerTitle }}</h2>
          <button class="close" type="button" aria-label="关闭" @click="drawerOpen = false">×</button>
        </header>

        <div class="drawer-body">
          <label class="row">
            <span>名称</span>
            <input v-model="form.name" type="text" maxlength="64" placeholder="如：我的 DeepSeek" required />
          </label>

          <label class="row">
            <span>Provider</span>
            <select v-model="form.provider">
              <option v-for="item in PROVIDERS" :key="item.value" :value="item.value">
                {{ item.label }}
              </option>
            </select>
          </label>

          <label class="row">
            <span>Base URL</span>
            <input v-model="form.base_url" type="text" maxlength="512" placeholder="https://api.deepseek.com/v1" required />
          </label>

          <label class="row">
            <span>API Key</span>
            <input
              v-model="form.api_key"
              type="password"
              autocomplete="new-password"
              :placeholder="editingId == null ? 'sk-...' : '不修改则留空'"
            />
            <small class="muted">仅写入，接口与页面均不回显明文。</small>
          </label>

          <div class="row">
            <span>模型清单</span>
            <div class="model-tags">
              <span v-for="(model, index) in form.models" :key="model.model_key" class="model-tag">
                {{ model.model_key }}
                <button type="button" aria-label="移除模型" @click="removeModel(index)">×</button>
              </span>
              <span v-if="!form.models.length" class="muted">尚未添加模型</span>
            </div>
            <div class="model-add">
              <input
                v-model="modelDraft"
                type="text"
                placeholder="输入模型名，如 deepseek-chat"
                @keydown.enter.prevent="addModel"
              />
              <button class="btn btn-sm" type="button" @click="addModel">添加</button>
            </div>
          </div>

          <div class="row inline">
            <label><input v-model="form.is_default" type="checkbox" /> 设为默认模型 API</label>
            <label><input v-model="form.enabled" type="checkbox" /> 启用</label>
          </div>

          <p v-if="testText" class="ok size-12">{{ testText }}</p>
          <p v-if="drawerError" class="error size-12">{{ drawerError }}</p>
        </div>

        <footer class="drawer-foot">
          <button class="btn" type="button" :disabled="testing" @click="testInDrawer">
            {{ testing ? '测试中…' : '测试连接' }}
          </button>
          <span class="spacer"></span>
          <button class="btn" type="button" @click="drawerOpen = false">取消</button>
          <button class="btn-primary" type="submit" :disabled="saving">
            {{ saving ? '保存中…' : '保存' }}
          </button>
        </footer>
      </form>
    </div>
  </section>
</template>

<style scoped>
.demo-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  padding: 9px 12px;
  border: 1px solid rgba(210, 153, 34, 0.35);
  border-radius: var(--radius-sm);
  background: var(--warn-soft);
  color: var(--warn);
  font-size: 12.5px;
}

.demo-badge {
  padding: 0 8px;
  border-radius: 999px;
  background: rgba(210, 153, 34, 0.2);
  font-size: 11px;
  line-height: 19px;
}

.notice {
  margin-bottom: 10px;
  font-size: 12.5px;
}

.name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.mono {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-secondary);
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.test-time {
  display: block;
  font-size: 10.5px;
  margin-top: 2px;
}

.ops {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.drawer-mask {
  position: fixed;
  inset: 0;
  z-index: 60;
  background: rgba(5, 7, 10, 0.6);
  display: flex;
  justify-content: flex-end;
}

.drawer {
  width: min(480px, 94vw);
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border-left: 1px solid var(--border-strong);
  box-shadow: var(--shadow-pop);
}

.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 20px 12px;
  border-bottom: 1px solid var(--border-color);
}

.drawer-head h2 {
  margin: 0;
  font-size: 16px;
}

.close {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text-muted);
  font-size: 18px;
  cursor: pointer;
}

.close:hover {
  background: var(--bg-hover);
  color: var(--text-main);
}

.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.row > span {
  font-size: 12.5px;
  color: var(--text-secondary);
}

.row small {
  font-size: 11px;
  line-height: 1.5;
}

.row.inline {
  flex-direction: row;
  gap: 16px;
  flex-wrap: wrap;
}

.row.inline label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--text-secondary);
}

.model-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 26px;
  padding: 6px 8px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-input);
}

.model-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--bg-elevated);
  color: var(--text-secondary);
  font-size: 11.5px;
  font-family: var(--font-mono);
}

.model-tag button {
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
}

.model-tag button:hover {
  color: var(--danger);
}

.model-add {
  display: flex;
  gap: 8px;
}

.model-add input {
  flex: 1;
}

.drawer-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid var(--border-color);
}

.spacer {
  flex: 1;
}

.size-12 {
  font-size: 12px;
}

@media (max-width: 768px) {
  .mono {
    max-width: 140px;
  }

  .table {
    display: block;
    overflow-x: auto;
  }
}
</style>

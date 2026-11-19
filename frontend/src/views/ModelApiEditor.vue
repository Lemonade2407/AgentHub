<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errorMessage, isRouteMissing } from '../api/http'
import { DEMO_MODEL_APIS } from '../data/demo'
import {
  PROVIDERS,
  providerLabel,
  type ModelApi,
  type ModelApiModel,
  type ModelApiTestResult,
} from '../types/api'

interface ModelDraft {
  id?: number
  model_key: string
  display_name: string
}

const route = useRoute()
const router = useRouter()

const rawId = computed(() => {
  const value = route.params.id
  return Array.isArray(value) ? value[0] : value
})
const isNew = computed(() => rawId.value === 'new')
const apiId = computed(() => Number(rawId.value))

const form = reactive({
  name: '',
  provider: 'deepseek',
  base_url: 'https://api.deepseek.com/v1',
  api_key: '',
  is_default: false,
  enabled: true,
  models: [] as ModelDraft[],
})

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const demoMode = ref(route.query.demo === '1')
const existing = ref<ModelApi | null>(null)
const error = ref('')
const message = ref('')
const testText = ref('')
const modelDraft = ref('')

function modelsOf(item: ModelApi): ModelApiModel[] {
  return item.models ?? item.model_api_models ?? []
}

function applyItem(item: ModelApi) {
  form.name = item.name
  form.provider = item.provider
  form.base_url = item.base_url
  form.api_key = ''
  form.is_default = item.is_default
  form.enabled = item.enabled
  form.models = modelsOf(item).map((model) => ({
    id: model.id,
    model_key: model.model_key,
    display_name: model.display_name || model.model_key,
  }))
}

function demoItem(): ModelApi | undefined {
  return DEMO_MODEL_APIS.find((entry) => entry.id === apiId.value)
}

async function loadItem() {
  if (isNew.value) return
  loading.value = true
  error.value = ''
  try {
    if (demoMode.value) {
      const item = demoItem()
      if (item) {
        existing.value = item
        applyItem(item)
      } else {
        error.value = '模型 API 不存在'
      }
      return
    }
    const item = await api.get<ModelApi>(`/api/model-apis/${apiId.value}`)
    existing.value = item
    applyItem(item)
  } catch (e) {
    if (isRouteMissing(e)) {
      demoMode.value = true
      const item = demoItem()
      if (item) {
        existing.value = item
        applyItem(item)
      } else {
        error.value = '模型 API 不存在'
      }
    } else {
      error.value = errorMessage(e, '加载失败')
    }
  } finally {
    loading.value = false
  }
}

function addModel() {
  const key = modelDraft.value.trim()
  if (!key) return
  if (form.models.some((model) => model.model_key === key)) {
    modelDraft.value = ''
    return
  }
  form.models.push({ model_key: key, display_name: key })
  modelDraft.value = ''
}

function removeModel(index: number) {
  form.models.splice(index, 1)
}

function saveDemo() {
  const models: ModelApiModel[] = form.models.map((model, index) => ({
    id: model.id ?? Date.now() + index,
    model_key: model.model_key,
    display_name: model.display_name || model.model_key,
    enabled: true,
  }))
  if (isNew.value) {
    DEMO_MODEL_APIS.push({
      id: Date.now(),
      name: form.name.trim(),
      provider: form.provider,
      base_url: form.base_url.trim(),
      api_key_hint: form.api_key.slice(-4) || null,
      is_default: form.is_default,
      enabled: form.enabled,
      last_test_at: null,
      last_test_ok: null,
      last_error: null,
      models,
    })
  } else {
    const target = demoItem()
    if (target) {
      target.name = form.name.trim()
      target.provider = form.provider
      target.base_url = form.base_url.trim()
      target.is_default = form.is_default
      target.enabled = form.enabled
      target.models = models
    }
  }
}

async function save() {
  error.value = ''
  message.value = ''
  if (!form.name.trim()) {
    error.value = '请填写名称'
    return
  }
  if (!form.base_url.trim()) {
    error.value = '请填写 Base URL'
    return
  }
  if (isNew.value && !form.api_key.trim() && !demoMode.value) {
    error.value = '新建时 API Key 必填'
    return
  }

  saving.value = true
  try {
    if (demoMode.value) {
      saveDemo()
      await router.push('/settings/models')
      return
    }

    try {
      if (isNew.value) {
        const created = await api.post<ModelApi>('/api/model-apis', {
          name: form.name.trim(),
          provider: form.provider,
          base_url: form.base_url.trim(),
          api_key: form.api_key.trim(),
          is_default: form.is_default,
          enabled: form.enabled,
        })
        for (const model of form.models) {
          await api.post(`/api/model-apis/${created.id}/models`, {
            model_key: model.model_key,
            display_name: model.display_name || model.model_key,
          })
        }
        await router.push('/settings/models')
      } else {
        const payload: Record<string, unknown> = {
          name: form.name.trim(),
          provider: form.provider,
          base_url: form.base_url.trim(),
          is_default: form.is_default,
          enabled: form.enabled,
        }
        if (form.api_key.trim()) payload.api_key = form.api_key.trim()
        await api.put(`/api/model-apis/${apiId.value}`, payload)

        const originalModels = existing.value ? modelsOf(existing.value) : []
        const keptIds = new Set(form.models.map((model) => model.id).filter(Boolean))
        for (const model of originalModels) {
          if (model.id != null && !keptIds.has(model.id)) {
            await api.del(`/api/model-apis/${apiId.value}/models/${model.id}`)
          }
        }
        for (const model of form.models) {
          if (model.id == null) {
            await api.post(`/api/model-apis/${apiId.value}/models`, {
              model_key: model.model_key,
              display_name: model.display_name || model.model_key,
            })
          }
        }
        message.value = '保存成功'
        await loadItem()
      }
    } catch (e) {
      if (isRouteMissing(e)) {
        demoMode.value = true
        saveDemo()
        await router.push('/settings/models')
      } else {
        throw e
      }
    }
  } catch (e) {
    error.value = errorMessage(e, '保存失败')
  } finally {
    saving.value = false
  }
}

async function test() {
  testText.value = ''
  error.value = ''
  if (isNew.value) {
    error.value = '请先保存后再测试连接'
    return
  }
  if (demoMode.value) {
    testText.value = '示例数据暂不支持连接测试'
    return
  }
  testing.value = true
  try {
    const result = await api.post<ModelApiTestResult>(`/api/model-apis/${apiId.value}/test`)
    if (result.ok) {
      for (const key of result.models ?? []) {
        if (!form.models.some((model) => model.model_key === key)) {
          form.models.push({ model_key: key, display_name: key })
        }
      }
      testText.value = `连接成功${result.latency_ms != null ? ` · ${result.latency_ms}ms` : ''}${
        result.models?.length ? ` · 发现 ${result.models.length} 个模型` : ''
      }`
    } else {
      error.value = `连接失败：${result.error ?? '未知错误'}`
    }
  } catch (e) {
    error.value = `连接失败：${errorMessage(e)}`
  } finally {
    testing.value = false
  }
}

async function remove() {
  if (!window.confirm(`确定删除「${form.name}」？被 Agent 引用时会被拒绝。`)) return
  error.value = ''
  try {
    if (demoMode.value) {
      const index = DEMO_MODEL_APIS.findIndex((entry) => entry.id === apiId.value)
      if (index >= 0) DEMO_MODEL_APIS.splice(index, 1)
    } else {
      await api.del(`/api/model-apis/${apiId.value}`)
    }
    await router.push('/settings/models')
  } catch (e) {
    error.value = errorMessage(e, '删除失败')
  }
}

onMounted(loadItem)
</script>

<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">{{ isNew ? '新建模型 API' : form.name || '编辑模型 API' }}</h1>
        <p v-if="!isNew && !loading" class="muted page-desc">
          {{ providerLabel(form.provider) }} · {{ form.base_url }}
        </p>
      </div>
      <div class="header-actions">
        <button class="btn" type="button" @click="router.push('/settings/models')">返回列表</button>
        <button v-if="!isNew" class="btn" type="button" :disabled="testing" @click="test">
          {{ testing ? '测试中…' : '测试连接' }}
        </button>
        <button v-if="!isNew" class="btn danger" type="button" :disabled="saving" @click="remove">
          删除
        </button>
      </div>
    </header>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="message" class="ok">{{ message }}</p>
    <p v-if="testText" class="ok">{{ testText }}</p>
    <p v-if="loading" class="muted">加载中…</p>

    <form v-if="!loading" class="editor" @submit.prevent="save">
      <div class="row two">
        <label>
          <span>名称</span>
          <input v-model="form.name" type="text" maxlength="64" placeholder="例如：我的 DeepSeek" required />
        </label>
        <label>
          <span>Provider</span>
          <select v-model="form.provider">
            <option v-for="item in PROVIDERS" :key="item.value" :value="item.value">
              {{ item.label }}
            </option>
          </select>
        </label>
      </div>

      <label class="row">
        <span>Base URL</span>
        <input
          v-model="form.base_url"
          type="text"
          maxlength="512"
          placeholder="例如：https://api.deepseek.com/v1"
          required
        />
      </label>

      <label class="row">
        <span>API Key</span>
        <input
          v-model="form.api_key"
          type="password"
          autocomplete="new-password"
          :placeholder="isNew ? '例如：sk-...' : '不修改则留空'"
        />
        <small class="field-hint">仅写入，页面不会回显明文</small>
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
            placeholder="输入模型名，例如：deepseek-chat"
            @keydown.enter.prevent="addModel"
          />
          <button class="btn btn-sm" type="button" @click="addModel">添加</button>
        </div>
      </div>

      <div class="row two">
        <label class="check">
          <input v-model="form.is_default" type="checkbox" />
          设为默认模型 API
        </label>
        <label class="check">
          <input v-model="form.enabled" type="checkbox" />
          启用
        </label>
      </div>

      <div class="actions">
        <button class="btn-primary" type="submit" :disabled="saving">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </div>
    </form>
  </section>
</template>

<style scoped>
.header-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.editor {
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 18px;
  max-width: 820px;
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

.row .check {
  flex-direction: row;
  align-items: center;
  gap: 8px;
}

span {
  font-size: 13px;
  font-weight: 600;
}

input[type='text'],
input[type='password'],
select {
  padding: 8px 10px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-family: inherit;
  font-size: 13px;
  width: 100%;
  box-sizing: border-box;
}

.model-tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  padding: 6px 8px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
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
  font-weight: 400;
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

.actions {
  display: flex;
  gap: 10px;
}

@media (max-width: 700px) {
  .row.two {
    grid-template-columns: 1fr;
  }
}
</style>

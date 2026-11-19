<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, errorMessage, formatDateTime, isRouteMissing } from '../api/http'
import { DEMO_MODEL_APIS } from '../data/demo'
import {
  providerLabel,
  type ModelApi,
  type ModelApiModel,
  type ModelApiTestResult,
  type Page,
} from '../types/api'

const router = useRouter()

const items = ref<ModelApi[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
const demoMode = ref(false)
const busyId = ref<number | null>(null)

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
  router.push(demoMode.value ? '/settings/models/new?demo=1' : '/settings/models/new')
}

function openEdit(item: ModelApi) {
  router.push(`/settings/models/${item.id}${demoMode.value ? '?demo=1' : ''}`)
}

async function runTest(item: ModelApi) {
  if (demoMode.value) {
    flash('示例数据暂不支持连接测试')
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

async function remove(item: ModelApi) {
  if (!window.confirm(`确定删除「${item.name}」？被 Agent 引用时会被拒绝。`)) return
  if (demoMode.value) {
    const index = DEMO_MODEL_APIS.findIndex((entry) => entry.id === item.id)
    if (index >= 0) DEMO_MODEL_APIS.splice(index, 1)
    items.value = DEMO_MODEL_APIS
    flash('示例数据已删除（刷新页面后恢复）')
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
      <button class="btn-primary" type="button" @click="openCreate">新建模型 API</button>
    </header>

    <div v-if="demoMode" class="demo-banner">
      <span class="demo-badge">示例数据</span>
      模型 API 暂时不可用，当前展示示例数据，修改不会保存。
    </div>

    <p v-if="error" class="error-box">{{ error }}</p>
    <p v-if="notice" class="ok notice">{{ notice }}</p>
    <p v-if="loading" class="muted">加载中…</p>

    <div v-if="!loading && items.length" class="grid">
      <article v-for="item in items" :key="item.id" class="api-card">
        <div class="card-head">
          <div class="title-block">
            <h3>{{ item.name }}</h3>
            <span class="muted">{{ providerLabel(item.provider) }}</span>
          </div>
          <span v-if="item.is_default" class="badge on">默认</span>
        </div>

        <code class="endpoint">{{ item.base_url }}</code>

        <div class="facts">
          <span class="fact"><em>Key</em>{{ maskedKey(item) }}</span>
          <span class="fact"><em>模型</em>{{ modelsOf(item).length }}</span>
          <span class="badge" :class="testBadge(item).cls">{{ testBadge(item).label }}</span>
        </div>

        <span class="muted time">
          {{ item.last_test_at ? formatDateTime(item.last_test_at) : '尚未测试' }}
        </span>

        <div class="card-foot">
          <span v-if="!item.enabled" class="badge off">停用</span>
          <span v-else class="muted">启用</span>
          <div class="ops">
            <button class="btn btn-sm" type="button" :disabled="busyId === item.id" @click="runTest(item)">
              {{ busyId === item.id ? '测试中…' : '测试连接' }}
            </button>
            <button class="btn btn-sm" type="button" @click="openEdit(item)">编辑</button>
            <button
              class="btn btn-sm btn-danger"
              type="button"
              :disabled="busyId === item.id"
              @click="remove(item)"
            >
              删除
            </button>
          </div>
        </div>
      </article>
    </div>

    <p v-else-if="!loading" class="empty">
      还没有模型 API，点击右上角「新建模型 API」。
    </p>
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

.api-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 16px;
  transition: border-color 0.15s ease;
}

.api-card:hover {
  border-color: var(--border-strong);
}

.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.title-block h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  word-break: break-word;
}

.title-block .muted {
  font-size: 11px;
}

.endpoint {
  display: block;
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.facts {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  font-size: 11.5px;
  color: var(--text-secondary);
}

.fact em {
  font-style: normal;
  color: var(--text-muted);
  margin-right: 4px;
}

.time {
  font-size: 11px;
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

.ops {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
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

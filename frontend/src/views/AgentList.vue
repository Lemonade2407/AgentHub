<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

// DTO 与 AgentHub_接口契约文档.md §3.1 / §4.1.2 一致（snake_case，前端不做驼峰转换）
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

interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

const agents = ref<Agent[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const loading = ref(false)
const error = ref('')

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}

async function loadAgents() {
  loading.value = true
  error.value = ''
  const params = new URLSearchParams({
    page: String(page.value),
    page_size: String(pageSize.value),
  })
  if (keyword.value.trim()) {
    params.set('keyword', keyword.value.trim())
  }
  try {
    const resp = await fetch(`/api/agents?${params.toString()}`)
    if (!resp.ok) {
      const body = await resp.json().catch(() => null)
      // 统一错误响应见契约文档 §1.4
      throw new Error(body?.message ?? `HTTP ${resp.status}`)
    }
    const data: Page<Agent> = await resp.json()
    agents.value = data.items
    total.value = data.total
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  loadAgents()
}

function goPage(p: number) {
  if (p < 1 || p > totalPages.value) return
  page.value = p
  loadAgents()
}

onMounted(loadAgents)
</script>

<template>
  <section class="page">
    <div class="header">
      <h1>Agent 列表</h1>
      <router-link to="/agents/new" class="btn-primary">新建 Agent</router-link>
    </div>

    <div class="toolbar">
      <input
        v-model="keyword"
        type="text"
        placeholder="按名称搜索"
        @keyup.enter="search"
      />
      <button class="btn" @click="search">搜索</button>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="loading" class="muted">加载中…</p>

    <table v-if="!loading && agents.length" class="table">
      <thead>
        <tr>
          <th>ID</th>
          <th>名称</th>
          <th>模型</th>
          <th>最大步数</th>
          <th>绑定工具</th>
          <th>状态</th>
          <th>创建时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="a in agents" :key="a.id">
          <td>{{ a.id }}</td>
          <td>{{ a.name }}</td>
          <td><code>{{ a.model }}</code></td>
          <td>{{ a.max_steps }}</td>
          <td>{{ a.tool_ids.length }}</td>
          <td>
            <span class="badge" :class="a.enabled ? 'on' : 'off'">
              {{ a.enabled ? '启用' : '停用' }}
            </span>
          </td>
          <td>{{ formatTime(a.created_at) }}</td>
          <td>
            <router-link :to="`/agents/${a.id}`">编辑</router-link>
          </td>
        </tr>
      </tbody>
    </table>

    <p v-else-if="!loading" class="muted">暂无 Agent，点击右上角"新建 Agent"创建。</p>

    <div v-if="!loading && total > 0" class="pager">
      <button class="btn" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
      <span class="muted">第 {{ page }} / {{ totalPages }} 页 · 共 {{ total }} 条</span>
      <button class="btn" :disabled="page >= totalPages" @click="goPage(page + 1)">下一页</button>
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

.toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.toolbar input {
  padding: 6px 10px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  min-width: 240px;
}

.btn {
  padding: 6px 14px;
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
  text-decoration: none;
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

.badge {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
}

.badge.on {
  background: #e6f4ea;
  color: #1a7f37;
}

.badge.off {
  background: #f0f2f5;
  color: #6e7781;
}

.error {
  color: #d1242f;
}

.pager {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
}
</style>

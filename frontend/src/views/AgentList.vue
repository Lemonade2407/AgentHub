<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage, formatDateTime } from '../api/http'
import type { Agent, Page } from '../types/api'

const agents = ref<Agent[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const loading = ref(false)
const error = ref('')
const busyId = ref<number | null>(null)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

async function loadAgents() {
  loading.value = true
  error.value = ''
  const params = new URLSearchParams({
    page: String(page.value),
    page_size: String(pageSize.value),
  })
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  try {
    const data = await api.get<Page<Agent>>(`/api/agents?${params.toString()}`)
    agents.value = data.items
    total.value = data.total
  } catch (e) {
    error.value = errorMessage(e, 'Agent 列表加载失败')
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  void loadAgents()
}

function goPage(next: number) {
  if (next < 1 || next > totalPages.value) return
  page.value = next
  void loadAgents()
}

async function removeAgent(agent: Agent) {
  if (!window.confirm(`确定删除「${agent.name}」？删除后不会再出现在列表中。`)) return
  busyId.value = agent.id
  error.value = ''
  try {
    await api.del(`/api/agents/${agent.id}`)
    if (agents.value.length === 1 && page.value > 1) page.value -= 1
    await loadAgents()
  } catch (e) {
    error.value = errorMessage(e, '删除失败')
  } finally {
    busyId.value = null
  }
}

onMounted(loadAgents)
</script>

<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">Agents</h1>
      </div>
      <div class="head-actions">
        <router-link to="/chat" class="btn">工作台</router-link>
        <router-link to="/agents/new" class="btn-primary">新建 Agent</router-link>
      </div>
    </header>

    <div class="toolbar">
      <input v-model="keyword" type="search" placeholder="按名称搜索" @keyup.enter="search" />
      <button class="btn" type="button" @click="search">搜索</button>
      <span class="muted count">共 {{ total }} 条</span>
    </div>

    <p v-if="error" class="error-box">{{ error }}</p>
    <p v-if="loading" class="muted">加载中…</p>

    <div v-if="!loading && agents.length" class="grid">
      <article v-for="agent in agents" :key="agent.id" class="agent-card">
        <div class="card-head">
          <div class="title-block">
            <h3>{{ agent.name }}</h3>
            <span v-if="agent.description" class="desc">{{ agent.description }}</span>
          </div>
          <span class="badge" :class="agent.enabled ? 'on' : 'off'">
            {{ agent.enabled ? '启用' : '停用' }}
          </span>
        </div>

        <div class="facts">
          <span class="fact"><em>模型</em><code>{{ agent.model }}</code></span>
          <span class="fact"><em>步数</em>{{ agent.max_steps }}</span>
          <span class="fact"><em>工具</em>{{ agent.tool_ids.length }}</span>
        </div>

        <div class="card-foot">
          <span class="muted time">更新于 {{ formatDateTime(agent.updated_at) }}</span>
          <div class="ops">
            <router-link :to="`/agents/${agent.id}`" class="btn btn-sm">编辑</router-link>
            <router-link :to="`/chat?agent=${agent.id}`" class="btn btn-sm">运行</router-link>
            <button
              class="btn btn-sm btn-danger"
              type="button"
              :disabled="busyId === agent.id"
              @click="removeAgent(agent)"
            >
              {{ busyId === agent.id ? '删除中…' : '删除' }}
            </button>
          </div>
        </div>
      </article>
    </div>

    <p v-else-if="!loading" class="empty">
      还没有 Agent，点击右上角「新建 Agent」。
    </p>

    <div v-if="!loading && total > 0" class="pager">
      <button class="btn btn-sm" type="button" :disabled="page <= 1" @click="goPage(page - 1)">
        上一页
      </button>
      <span class="muted">第 {{ page }} / {{ totalPages }} 页</span>
      <button class="btn btn-sm" type="button" :disabled="page >= totalPages" @click="goPage(page + 1)">
        下一页
      </button>
    </div>
  </section>
</template>

<style scoped>
.head-actions {
  display: flex;
  gap: 8px;
}

.count {
  margin-left: auto;
  font-size: 12px;
}

.agent-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 16px;
  transition: border-color 0.15s ease;
}

.agent-card:hover {
  border-color: var(--border-strong);
}

.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.title-block {
  min-width: 0;
}

.title-block h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  word-break: break-word;
}

.desc {
  display: block;
  margin-top: 2px;
  font-size: 11.5px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.facts {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 11.5px;
  color: var(--text-secondary);
}

.fact {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
}

.fact em {
  font-style: normal;
  color: var(--text-muted);
}

.fact code {
  font-size: 11px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 180px;
}

.card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid var(--border-color);
}

.time {
  font-size: 11px;
}

.ops {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.pager {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
}
</style>

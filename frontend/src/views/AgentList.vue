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
      <span class="muted count">共 {{ total }} 个</span>
    </div>

    <p v-if="error" class="error-box">{{ error }}</p>
    <p v-if="loading" class="muted">加载中…</p>

    <table v-if="!loading && agents.length" class="table">
      <thead>
        <tr>
          <th>ID</th>
          <th>名称</th>
          <th>模型</th>
          <th>最大步数</th>
          <th>工具</th>
          <th>状态</th>
          <th>更新时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="agent in agents" :key="agent.id">
          <td class="muted">{{ agent.id }}</td>
          <td>
            <div class="name-cell">
              <strong>{{ agent.name }}</strong>
              <span v-if="agent.description" class="desc">{{ agent.description }}</span>
            </div>
          </td>
          <td><code class="model">{{ agent.model }}</code></td>
          <td>{{ agent.max_steps }}</td>
          <td>{{ agent.tool_ids.length }}</td>
          <td>
            <span class="badge" :class="agent.enabled ? 'on' : 'off'">
              {{ agent.enabled ? '启用' : '停用' }}
            </span>
          </td>
          <td class="muted time">{{ formatDateTime(agent.updated_at) }}</td>
          <td class="ops">
            <router-link :to="`/agents/${agent.id}`" class="btn btn-sm">编辑</router-link>
            <router-link :to="`/chat?agent=${agent.id}`" class="btn btn-sm">运行</router-link>
          </td>
        </tr>
      </tbody>
    </table>

    <p v-else-if="!loading" class="empty">
      暂无 Agent，点击右上角「新建 Agent」。
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

.name-cell {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.name-cell strong {
  font-weight: 500;
}

.desc {
  font-size: 11.5px;
  color: var(--text-muted);
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model {
  font-size: 11.5px;
  color: var(--text-secondary);
}

.time {
  white-space: nowrap;
  font-size: 11.5px;
}

.ops {
  display: flex;
  gap: 6px;
}

.pager {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
}
</style>

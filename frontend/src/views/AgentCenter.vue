<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage, isRouteMissing, relativeTime } from '../api/http'
import PublishDialog from '../components/PublishDialog.vue'
import { DEMO_PUBLICATIONS } from '../data/demo'
import { showNotice } from '../stores/ui'
import type { Agent, Page, Publication } from '../types/api'
import { SKILL_CATEGORIES, categoryLabel } from '../types/skill'

type Tab = 'agents' | 'center'

const tab = ref<Tab>('agents')
const agents = ref<Agent[]>([])
const items = ref<Publication[]>([])
const publishedByAgent = ref<Map<number, Publication>>(new Map())
const publishTarget = ref<Agent | null>(null)
const total = ref(0)
const page = ref(1)
const pageSize = 12
const keyword = ref('')
const category = ref('')
const sort = ref<'latest' | 'popular'>('latest')
const loading = ref(false)
const error = ref('')
const demoMode = ref(false)
const busyId = ref<number | null>(null)
const liked = ref<Set<number>>(new Set())

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

function filterDemo(): Publication[] {
  const query = keyword.value.trim().toLowerCase()
  let list = [...DEMO_PUBLICATIONS]
  if (query) {
    list = list.filter((item) =>
      `${item.title} ${item.summary}`.toLowerCase().includes(query),
    )
  }
  if (category.value) list = list.filter((item) => item.category === category.value)
  list.sort((a, b) => {
    if (sort.value === 'popular') return b.install_count - a.install_count
    return Date.parse(b.published_at ?? '') - Date.parse(a.published_at ?? '')
  })
  return list
}

async function load() {
  loading.value = true
  error.value = ''

  if (tab.value === 'agents') {
    demoMode.value = false
    const params = new URLSearchParams({
      page: String(page.value),
      page_size: String(pageSize),
    })
    if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
    try {
      const data = await api.get<Page<Agent>>(`/api/agents?${params.toString()}`)
      agents.value = data.items
      total.value = data.total
    } catch (e) {
      error.value = errorMessage(e, '我的 Agents 加载失败')
    } finally {
      loading.value = false
    }
    void loadMyPublications()
    return
  }

  const params = new URLSearchParams({ page: String(page.value), page_size: String(pageSize) })
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  if (category.value) params.set('category', category.value)
  if (tab.value === 'center') params.set('sort', sort.value)

  const path = '/api/agent-center'

  try {
    const raw = await api.get<Publication[] | Page<Publication>>(`${path}?${params.toString()}`)
    const list = Array.isArray(raw) ? raw : raw.items
    items.value = list
    total.value = Array.isArray(raw) ? raw.length : raw.total
    demoMode.value = false
  } catch (e) {
    if (isRouteMissing(e)) {
      demoMode.value = true
      const list = filterDemo()
      total.value = list.length
      items.value = list.slice((page.value - 1) * pageSize, page.value * pageSize)
    } else {
      error.value = errorMessage(e, 'Agent Center 加载失败')
    }
  } finally {
    loading.value = false
  }
}

async function loadMyPublications() {
  try {
    const data = await api.get<Page<Publication>>('/api/agent-center/mine?page=1&page_size=100')
    const map = new Map<number, Publication>()
    for (const pub of data.items) {
      if (pub.source_agent_id != null && pub.status === 'published') {
        map.set(pub.source_agent_id, pub)
      }
    }
    publishedByAgent.value = map
  } catch {
    publishedByAgent.value = new Map()
  }
}

function publishedVersion(agentId: number): string {
  return publishedByAgent.value.get(agentId)?.version ?? ''
}

function nextVersion(version: string): string {
  const parts = version.split('.')
  if (parts.length === 3 && parts.every((part) => /^\d+$/.test(part))) {
    return `${parts[0]}.${parts[1]}.${Number(parts[2]) + 1}`
  }
  return version
}

function openPublish(agent: Agent) {
  publishTarget.value = agent
}

async function onPublished() {
  publishTarget.value = null
  showNotice('发布成功，已出现在广场')
  await load()
}

function switchTab(next: Tab) {
  if (tab.value === next) return
  tab.value = next
  page.value = 1
  void load()
}

function search() {
  page.value = 1
  void load()
}

function goPage(next: number) {
  if (next < 1 || next > totalPages.value) return
  page.value = next
  void load()
}

function initial(text: string): string {
  return (text || '?').slice(0, 1).toUpperCase()
}

function skillCount(item: Publication): number {
  return item.snapshot?.skills?.length ?? 0
}

function toolCount(item: Publication): number {
  return item.snapshot?.tools?.length ?? 0
}

async function toggleLike(item: Publication) {
  const isLiked = liked.value.has(item.id)
  if (demoMode.value) {
    if (isLiked) {
      liked.value.delete(item.id)
      item.like_count = Math.max(0, item.like_count - 1)
    } else {
      liked.value.add(item.id)
      item.like_count += 1
    }
    liked.value = new Set(liked.value)
    return
  }
  busyId.value = item.id
  try {
    await api.post(`/api/agent-center/${item.id}/${isLiked ? 'unlike' : 'like'}`)
    if (isLiked) {
      liked.value.delete(item.id)
      item.like_count = Math.max(0, item.like_count - 1)
    } else {
      liked.value.add(item.id)
      item.like_count += 1
    }
    liked.value = new Set(liked.value)
  } catch (e) {
    error.value = errorMessage(e, '点赞失败')
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
        <h1 class="page-title">Agent Center</h1>
      </div>
      <router-link to="/agents" class="btn-primary">选择 Agent 去发布</router-link>
    </header>

    <div class="tabs">
      <button class="tab" :class="{ active: tab === 'agents' }" type="button" @click="switchTab('agents')">
        我的 Agents
      </button>
      <button class="tab" :class="{ active: tab === 'center' }" type="button" @click="switchTab('center')">
        广场
      </button>
    </div>

    <div class="toolbar">
      <input v-model="keyword" type="search" placeholder="搜索名称或简介" @keyup.enter="search" />
      <select v-if="tab === 'center'" v-model="category" @change="search">
        <option value="">全部分类</option>
        <option v-for="item in SKILL_CATEGORIES" :key="item.value" :value="item.value">
          {{ item.label }}
        </option>
      </select>
      <select v-if="tab === 'center'" v-model="sort" @change="search">
        <option value="latest">最新</option>
        <option value="popular">最热</option>
      </select>
      <button class="btn" type="button" @click="search">搜索</button>
    </div>

    <div v-if="demoMode" class="demo-banner">
      <span class="demo-badge">示例数据</span>
      广场内容暂时无法加载，当前展示示例数据。
    </div>

    <p v-if="error" class="error-box">{{ error }}</p>
    <p v-if="loading" class="muted">加载中…</p>

    <div v-if="!loading && tab === 'agents' && agents.length" class="grid">
      <article v-for="agent in agents" :key="agent.id" class="pub-card">
        <router-link :to="`/agents/${agent.id}`" class="card-main">
          <div class="card-top">
            <span class="icon">{{ initial(agent.name) }}</span>
            <div class="title-block">
              <h3>{{ agent.name }}</h3>
              <span class="meta-line">
                {{ agent.enabled ? '启用中' : '已停用' }} · 更新于 {{ relativeTime(agent.updated_at) }}
              </span>
            </div>
            <span class="badge">{{ agent.model || '对话时选择' }}</span>
          </div>

          <p class="summary">{{ agent.description || '暂无简介' }}</p>

          <div class="facts">
            <span>{{ agent.skill_count ?? 0 }} Skill</span>
            <span>{{ agent.tool_ids.length }} 工具</span>
            <span>最多 {{ agent.max_steps }} 步</span>
          </div>
        </router-link>

        <footer class="card-foot">
          <span class="muted">ID {{ agent.id }}</span>
          <span v-if="publishedVersion(agent.id)" class="badge">
            已公开 v{{ publishedVersion(agent.id) }}
          </span>
          <button class="btn btn-sm" type="button" @click="openPublish(agent)">
            {{ publishedVersion(agent.id) ? '再次发布' : '公开' }}
          </button>
          <router-link :to="`/chat?agent=${agent.id}`" class="run-link">运行 →</router-link>
        </footer>
      </article>
    </div>

    <div v-else-if="!loading && tab === 'center' && items.length" class="grid">
      <article v-for="item in items" :key="item.id" class="pub-card">
        <router-link :to="`/agent-center/${item.id}`" class="card-main">
          <div class="card-top">
            <span class="icon">{{ initial(item.title) }}</span>
            <div class="title-block">
              <h3>{{ item.title }}</h3>
              <span class="meta-line">{{ item.owner_display_name || '匿名' }} · v{{ item.version }}</span>
            </div>
            <span class="badge">{{ categoryLabel(item.category) }}</span>
          </div>

          <p class="summary">{{ item.summary || '暂无简介' }}</p>

          <div class="facts">
            <span>{{ skillCount(item) }} Skill</span>
            <span>{{ toolCount(item) }} 工具</span>
            <span v-if="item.snapshot?.suggested_model" class="mono">
              {{ item.snapshot.suggested_model.provider }}/{{ item.snapshot.suggested_model.model_key }}
            </span>
          </div>
        </router-link>

        <footer class="card-foot">
          <span class="muted">{{ item.published_at ? relativeTime(item.published_at) : '未发布' }}</span>
          <span class="foot-stat">安装 {{ item.install_count }}</span>
          <button
            class="like"
            :class="{ active: liked.has(item.id) }"
            type="button"
            :disabled="busyId === item.id"
            @click="toggleLike(item)"
          >
            ♥ {{ item.like_count }}
          </button>
        </footer>
      </article>
    </div>

    <p v-else-if="!loading" class="empty">
      {{
        tab === 'agents'
          ? '还没有 Agent，去 Agents 页面新建一个。'
          : '广场暂无公开 Agent。'
      }}
    </p>

    <div v-if="!loading && total > 0" class="pager">
      <button class="btn btn-sm" type="button" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
      <span class="muted">第 {{ page }} / {{ totalPages }} 页 · 共 {{ total }} 条</span>
      <button class="btn btn-sm" type="button" :disabled="page >= totalPages" @click="goPage(page + 1)">
        下一页
      </button>
    </div>

    <PublishDialog
      v-if="publishTarget"
      :agent-id="publishTarget.id"
      :name="publishTarget.name"
      :description="publishTarget.description"
      :initial-version="
        publishedVersion(publishTarget.id) ? nextVersion(publishedVersion(publishTarget.id)) : '1.0.0'
      "
      @close="publishTarget = null"
      @published="onPublished"
    />
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

.pub-card {
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  transition: border-color 0.15s ease, transform 0.15s ease;
}

.pub-card:hover {
  border-color: var(--border-strong);
  transform: translateY(-1px);
}

.card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px 16px 10px;
  color: inherit;
}

.card-main:hover {
  color: inherit;
}

.card-top {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.icon {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--accent-soft);
  color: var(--accent-hover);
  font-weight: 700;
  font-size: 15px;
  flex-shrink: 0;
}

.title-block {
  flex: 1;
  min-width: 0;
}

.title-block h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meta-line {
  font-size: 11px;
  color: var(--text-muted);
}

.summary {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--text-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 40px;
}

.facts {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 11px;
  color: var(--text-muted);
}

.mono {
  font-family: var(--font-mono);
}

.card-foot {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px 12px;
  font-size: 11px;
  border-top: 1px solid var(--border-color);
}

.foot-stat {
  color: var(--text-secondary);
}

.like {
  margin-left: auto;
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 11.5px;
  font-family: inherit;
  cursor: pointer;
}

.like:hover,
.like.active {
  color: var(--danger);
}

.run-link {
  margin-left: auto;
  color: var(--accent-hover);
  font-size: 11.5px;
}

.run-link:hover {
  text-decoration: underline;
}

.pager {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 18px;
}
</style>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  SKILL_CATEGORIES,
  categoryLabel,
  statusLabel,
  visibilityLabel,
  type Page,
  type Skill,
} from '../types/skill'

type Tab = 'mine' | 'center'

const tab = ref<Tab>('mine')
const skills = ref<Skill[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(12)
const keyword = ref('')
const category = ref('')
const statusFilter = ref('')
const sort = ref('latest')

const loading = ref(false)
const error = ref('')
const message = ref('')
const busyId = ref<number | null>(null)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

function failMessage(resp: Response): Promise<string> {
  return resp
    .json()
    .catch(() => null)
    .then((body) => body?.message ?? `HTTP ${resp.status}`)
}

async function load() {
  loading.value = true
  error.value = ''
  const params = new URLSearchParams({
    page: String(page.value),
    page_size: String(pageSize.value),
  })
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  if (category.value) params.set('category', category.value)
  if (tab.value === 'mine' && statusFilter.value) params.set('status', statusFilter.value)
  if (tab.value === 'center') params.set('sort', sort.value)

  const path = tab.value === 'mine' ? '/api/skills' : '/api/skills/center'
  try {
    const resp = await fetch(`${path}?${params.toString()}`)
    if (!resp.ok) throw new Error(await failMessage(resp))
    const data: Page<Skill> = await resp.json()
    skills.value = data.items
    total.value = data.total
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function switchTab(next: Tab) {
  if (tab.value === next) return
  tab.value = next
  page.value = 1
  statusFilter.value = ''
  error.value = ''
  message.value = ''
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

async function action(skill: Skill, path: string, method: string, success: string) {
  busyId.value = skill.id
  error.value = ''
  message.value = ''
  try {
    const resp = await fetch(path, { method })
    if (!resp.ok) throw new Error(await failMessage(resp))
    message.value = success
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busyId.value = null
  }
}

function publish(skill: Skill) {
  void action(skill, `/api/skills/${skill.id}/publish`, 'POST', `已公开「${skill.name}」`)
}

function archive(skill: Skill) {
  void action(skill, `/api/skills/${skill.id}/archive`, 'POST', `已下架「${skill.name}」`)
}

async function remove(skill: Skill) {
  if (!window.confirm(`确定删除「${skill.name}」？被 Agent 挂载时无法删除。`)) return
  busyId.value = skill.id
  error.value = ''
  message.value = ''
  try {
    const resp = await fetch(`/api/skills/${skill.id}`, { method: 'DELETE' })
    if (!resp.ok) throw new Error(await failMessage(resp))
    message.value = `已删除「${skill.name}」`
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busyId.value = null
  }
}

async function install(skill: Skill) {
  busyId.value = skill.id
  error.value = ''
  message.value = ''
  try {
    const resp = await fetch(`/api/skills/${skill.id}/install`, { method: 'POST' })
    if (!resp.ok) throw new Error(await failMessage(resp))
    message.value = `已安装「${skill.name}」到我的 Skills，可在 Agent 编辑器中挂载`
    tab.value = 'mine'
    page.value = 1
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busyId.value = null
  }
}

function iconText(skill: Skill): string {
  return (skill.icon || skill.name || '?').slice(0, 1).toUpperCase()
}

onMounted(load)
</script>

<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">Skills Center</h1>
      </div>
      <router-link to="/skills/new" class="btn-primary">新建 Skill</router-link>
    </header>

    <div class="tabs">
      <button class="tab" :class="{ active: tab === 'mine' }" type="button" @click="switchTab('mine')">
        我的 Skills
      </button>
      <button class="tab" :class="{ active: tab === 'center' }" type="button" @click="switchTab('center')">
        广场
      </button>
    </div>

    <div class="toolbar">
      <input v-model="keyword" type="search" placeholder="按名称 / slug / 简介搜索" @keyup.enter="search" />
      <select v-model="category" @change="search">
        <option value="">全部分类</option>
        <option v-for="item in SKILL_CATEGORIES" :key="item.value" :value="item.value">
          {{ item.label }}
        </option>
      </select>
      <select v-if="tab === 'mine'" v-model="statusFilter" @change="search">
        <option value="">全部状态</option>
        <option value="draft">草稿</option>
        <option value="published">已公开</option>
        <option value="archived">已下架</option>
      </select>
      <select v-else v-model="sort" @change="search">
        <option value="latest">最新</option>
        <option value="popular">最热</option>
      </select>
      <button class="btn" type="button" @click="search">搜索</button>
    </div>

    <p v-if="error" class="error-box">{{ error }}</p>
    <p v-if="message" class="ok notice">{{ message }}</p>
    <p v-if="loading" class="muted">加载中…</p>

    <div v-if="!loading && skills.length" class="grid">
      <article v-for="skill in skills" :key="skill.id" class="skill-card">
        <div class="card-head">
          <span class="icon">{{ iconText(skill) }}</span>
          <div class="title">
            <h3>{{ skill.name }}</h3>
            <span class="muted">{{ skill.slug }} · v{{ skill.version }}</span>
          </div>
          <span class="badge" :class="skill.status">{{ statusLabel(skill.status) }}</span>
        </div>

        <p class="summary">{{ skill.summary || '暂无简介' }}</p>

        <div v-if="skill.tags.length" class="tags">
          <span v-for="tag in skill.tags" :key="tag" class="tag">{{ tag }}</span>
        </div>

        <div class="meta">
          <span>{{ categoryLabel(skill.category) }}</span>
          <span>{{ visibilityLabel(skill.visibility) }}</span>
          <span>{{ skill.tools.length }} 工具</span>
          <span>{{ skill.install_count }} 安装</span>
          <span v-if="tab === 'center'">by {{ skill.owner_display_name || '匿名' }}</span>
        </div>

        <div class="actions">
          <template v-if="tab === 'mine' || skill.owned">
            <router-link :to="`/skills/${skill.id}`" class="btn btn-sm">编辑</router-link>
            <button
              v-if="skill.status !== 'published'"
              class="btn btn-sm"
              type="button"
              :disabled="busyId === skill.id"
              @click="publish(skill)"
            >
              公开
            </button>
            <button v-else class="btn btn-sm" type="button" :disabled="busyId === skill.id" @click="archive(skill)">
              下架
            </button>
            <button
              class="btn btn-sm btn-danger"
              type="button"
              :disabled="busyId === skill.id"
              @click="remove(skill)"
            >
              删除
            </button>
          </template>
          <template v-else>
            <router-link :to="`/skills/${skill.id}`" class="btn btn-sm">查看</router-link>
            <button class="btn-primary btn-sm" type="button" :disabled="busyId === skill.id" @click="install(skill)">
              安装
            </button>
          </template>
        </div>
      </article>
    </div>

    <p v-else-if="!loading" class="empty">
      {{
        tab === 'mine'
          ? '还没有 Skill，点击右上角「新建 Skill」。'
          : '广场暂无公开 Skill。把 Skill 设为公开后，其他账号即可搜索与安装。'
      }}
    </p>

    <div v-if="!loading && total > 0" class="pager">
      <button class="btn btn-sm" type="button" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
      <span class="muted">第 {{ page }} / {{ totalPages }} 页 · 共 {{ total }} 条</span>
      <button class="btn btn-sm" type="button" :disabled="page >= totalPages" @click="goPage(page + 1)">
        下一页
      </button>
    </div>
  </section>
</template>

<style scoped>
.notice {
  margin-bottom: 10px;
  font-size: 12.5px;
}

.skill-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 16px;
  transition: border-color 0.15s ease;
}

.skill-card:hover {
  border-color: var(--border-strong);
}

.card-head {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--accent-soft);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  color: var(--accent-hover);
  flex-shrink: 0;
}

.title {
  flex: 1;
  min-width: 0;
}

.title h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  word-break: break-word;
}

.title .muted {
  font-size: 11px;
}

.summary {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 40px;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 11px;
  color: var(--text-muted);
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: auto;
  padding-top: 4px;
}

.pager {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
}
</style>

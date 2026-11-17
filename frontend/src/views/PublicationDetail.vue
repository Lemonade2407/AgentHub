<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, errorMessage, isRouteMissing, relativeTime } from '../api/http'
import InstallPrecheckDialog from '../components/InstallPrecheckDialog.vue'
import { findDemoPublication } from '../data/demo'
import type { Publication } from '../types/api'
import { categoryLabel } from '../types/skill'

const route = useRoute()
const publicationId = computed(() => Number(route.params.id))

const item = ref<Publication | null>(null)
const loading = ref(false)
const error = ref('')
const demoMode = ref(false)
const liked = ref(false)
const likeBusy = ref(false)
const installOpen = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  item.value = null
  try {
    item.value = await api.get<Publication>(`/api/agent-center/${publicationId.value}`)
    demoMode.value = false
  } catch (e) {
    if (isRouteMissing(e)) {
      const demo = findDemoPublication(publicationId.value)
      if (demo) {
        item.value = demo
        demoMode.value = true
      } else {
        error.value = '未找到该 Publication'
      }
    } else {
      error.value = errorMessage(e, 'Publication 加载失败')
    }
  } finally {
    loading.value = false
  }
}

async function toggleLike() {
  if (!item.value) return
  if (demoMode.value) {
    liked.value = !liked.value
    item.value.like_count += liked.value ? 1 : -1
    return
  }
  likeBusy.value = true
  try {
    await api.post(`/api/agent-center/${item.value.id}/${liked.value ? 'unlike' : 'like'}`)
    liked.value = !liked.value
    item.value.like_count += liked.value ? 1 : -1
  } catch (e) {
    error.value = errorMessage(e, '点赞失败')
  } finally {
    likeBusy.value = false
  }
}

function pretty(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

watch(publicationId, load)
onMounted(load)
</script>

<template>
  <section class="page">
    <router-link to="/agent-center" class="back">← 返回 Agent Center</router-link>

    <p v-if="loading" class="muted">加载中…</p>
    <p v-if="error" class="error-box">{{ error }}</p>

    <template v-if="item">
      <div v-if="demoMode" class="demo-banner">
        <span class="demo-badge">演示数据</span>
        Publication 详情接口（D：WP-3.1）尚未就绪，以下为演示快照。
      </div>

      <header class="detail-head">
        <div class="title-row">
          <span class="icon">{{ item.title.slice(0, 1) }}</span>
          <div>
            <h1 class="page-title">{{ item.title }}</h1>
            <p class="page-desc">{{ item.summary || '暂无简介' }}</p>
          </div>
          <span class="badge">{{ categoryLabel(item.category) }}</span>
        </div>
      </header>

      <div class="detail-layout">
        <div class="detail-main">
          <section class="block">
            <h2>Agent 定义</h2>
            <div class="kv">
              <span>名称</span>
              <strong>{{ item.snapshot.agent.name }}</strong>
              <span>最大步数</span>
              <strong>{{ item.snapshot.agent.max_steps }}</strong>
              <span>建议模型</span>
              <strong class="mono">
                {{
                  item.snapshot.suggested_model
                    ? `${item.snapshot.suggested_model.provider}/${item.snapshot.suggested_model.model_key}`
                    : '未指定'
                }}
              </strong>
            </div>
            <pre class="prompt">{{ item.snapshot.agent.system_prompt || '未设置 System Prompt' }}</pre>
          </section>

          <section class="block">
            <h2>Skill 依赖（{{ item.snapshot.skills.length }}）</h2>
            <p v-if="!item.snapshot.skills.length" class="muted">无 Skill 依赖。</p>
            <ul v-else class="dep-list">
              <li v-for="skill in item.snapshot.skills" :key="`${skill.slug}@${skill.version}`">
                <code>{{ skill.slug }}</code> · v{{ skill.version }}
                <span v-if="skill.params && Object.keys(skill.params).length" class="muted params">
                  参数 {{ pretty(skill.params) }}
                </span>
              </li>
            </ul>
          </section>

          <section class="block">
            <h2>工具依赖（{{ item.snapshot.tools.length }}）</h2>
            <p v-if="!item.snapshot.tools.length" class="muted">无工具依赖。</p>
            <ul v-else class="dep-list">
              <li v-for="tool in item.snapshot.tools" :key="`${tool.server_name}.${tool.remote_name}`">
                <code>{{ tool.server_name }}</code> / <code>{{ tool.remote_name }}</code>
                <span class="badge" :class="tool.required === false ? 'off' : 'published'">
                  {{ tool.required === false ? '可选' : '必填' }}
                </span>
                <span v-if="tool.endpoint" class="muted mono endpoint">{{ tool.endpoint }}</span>
              </li>
            </ul>
            <p class="muted hint">安装时不会自动注册 MCP Server，只提示需先注册同名 Server。</p>
          </section>
        </div>

        <aside class="detail-side">
          <div class="side-card">
            <div class="side-row">
              <span class="muted">作者</span>
              <span>{{ item.owner_display_name || '匿名' }}</span>
            </div>
            <div class="side-row">
              <span class="muted">版本</span>
              <span class="mono">v{{ item.version }}</span>
            </div>
            <div class="side-row">
              <span class="muted">发布时间</span>
              <span>{{ item.published_at ? relativeTime(item.published_at) : '未发布' }}</span>
            </div>
            <div class="side-row">
              <span class="muted">安装 / 点赞</span>
              <span>{{ item.install_count }} / {{ item.like_count }}</span>
            </div>

            <button class="btn-primary install" type="button" @click="installOpen = true">
              安装到我的 Agents
            </button>
            <button class="btn like-btn" :class="{ active: liked }" type="button" :disabled="likeBusy" @click="toggleLike">
              {{ liked ? '♥ 已点赞' : '♡ 点赞' }}
            </button>
            <p class="side-note">安装前会做依赖预检，缺失项会列成清单。</p>
          </div>
        </aside>
      </div>

      <InstallPrecheckDialog
        v-if="installOpen"
        :publication="item"
        :demo="demoMode"
        @close="installOpen = false"
      />
    </template>
  </section>
</template>

<style scoped>
.back {
  display: inline-block;
  margin-bottom: 14px;
  font-size: 12.5px;
  color: var(--text-muted);
}

.back:hover {
  color: var(--text-main);
}

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

.title-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.icon {
  width: 42px;
  height: 42px;
  border-radius: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--accent-soft);
  color: var(--accent-hover);
  font-size: 18px;
  font-weight: 700;
  flex-shrink: 0;
}

.detail-head {
  margin-bottom: 18px;
}

.detail-head .badge {
  margin-left: auto;
}

.detail-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 18px;
  align-items: start;
}

.detail-main {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.block {
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 16px;
}

.block h2 {
  margin: 0 0 12px;
  font-size: 13.5px;
  font-weight: 600;
}

.kv {
  display: grid;
  grid-template-columns: 80px 1fr;
  gap: 6px 10px;
  font-size: 12.5px;
  color: var(--text-secondary);
  margin-bottom: 12px;
}

.kv strong {
  color: var(--text-main);
  font-weight: 500;
}

.mono {
  font-family: var(--font-mono);
  font-size: 11.5px;
}

.prompt {
  margin: 0;
  padding: 12px;
  border-radius: var(--radius-sm);
  background: var(--bg-base);
  border: 1px solid var(--border-color);
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.7;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 320px;
  overflow-y: auto;
}

.dep-list {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 12.5px;
}

.params {
  display: block;
  font-size: 11px;
}

.endpoint {
  display: block;
  font-size: 11px;
  margin-top: 2px;
}

.hint {
  margin: 10px 0 0;
  font-size: 11.5px;
}

.detail-side {
  position: sticky;
  top: 16px;
}

.side-card {
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.side-row {
  display: flex;
  justify-content: space-between;
  font-size: 12.5px;
  color: var(--text-secondary);
}

.install {
  margin-top: 8px;
  width: 100%;
  height: 36px;
}

.like-btn {
  width: 100%;
  height: 32px;
}

.like-btn.active {
  color: var(--danger);
  border-color: rgba(240, 93, 93, 0.4);
}

.side-note {
  margin: 0;
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.5;
}

@media (max-width: 1024px) {
  .detail-layout {
    grid-template-columns: 1fr;
  }

  .detail-side {
    position: static;
  }
}
</style>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { relativeTime } from '../api/http'
import { conversations, removeConversation } from '../stores/conversations'
import { closeSidebar } from '../stores/ui'

interface NavItem {
  label: string
  path: string
  icon: string
}

interface NavGroup {
  label: string
  items: NavItem[]
}

const groups: NavGroup[] = [
  {
    label: '工作',
    items: [
      {
        label: '工作台',
        path: '/chat',
        icon: 'M21 11.5a8.5 8.5 0 0 1-8.5 8.5H7l-4 3V11.5A8.5 8.5 0 0 1 11.5 3h1A8.5 8.5 0 0 1 21 11.5Z',
      },
      {
        label: 'Agents',
        path: '/agents',
        icon: 'M12 3v3M5 8h14v11H5V8ZM9 13h.01M15 13h.01M9 17h6',
      },
    ],
  },
  {
    label: '资源',
    items: [
      {
        label: 'Skills Center',
        path: '/skills',
        icon: 'm12 3 2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2L12 3Z',
      },
      {
        label: 'Agent Center',
        path: '/agent-center',
        icon: 'M4 9h16l-1.4 10H5.4L4 9Zm0 0 2-4h12l2 4',
      },
      {
        label: 'MCP Hub',
        path: '/mcp',
        icon: 'M9 3v6M15 3v6M6 9h12v3a6 6 0 0 1-12 0V9ZM12 18v3',
      },
    ],
  },
  {
    label: '设置',
    items: [
      {
        label: '模型 API',
        path: '/settings/models',
        icon: 'M15 7a4 4 0 1 1-2.6 7L4 21H3v-3l8.5-8.5A4 4 0 0 1 15 7Z',
      },
    ],
  },
]

const route = useRoute()
const router = useRouter()

const historyItems = computed(() =>
  [...conversations.value].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
)

const menu = ref<{ id: string; x: number; y: number } | null>(null)
const menuStyle = computed(() => {
  if (!menu.value) return {}
  return {
    left: `${Math.min(menu.value.x, window.innerWidth - 150)}px`,
    top: `${Math.min(menu.value.y, window.innerHeight - 56)}px`,
  }
})

function isActive(path: string): boolean {
  if (path === '/chat') return route.path.startsWith('/chat')
  if (path === '/agents') return route.path.startsWith('/agents')
  if (path === '/skills') return route.path.startsWith('/skills')
  if (path === '/agent-center') return route.path.startsWith('/agent-center')
  return route.path === path
}

function newChat() {
  closeMenu()
  router.push('/chat')
}

function openConversation(id: string) {
  closeMenu()
  router.push(`/chat/${id}`)
}

function remove(id: string) {
  removeConversation(id)
  closeMenu()
  if (route.params.runId === id) {
    router.replace('/chat')
  }
}

function openMenu(event: MouseEvent, id: string) {
  menu.value = { id, x: event.clientX, y: event.clientY }
}

function closeMenu() {
  menu.value = null
}

// 清空历史：第一次点击进入确认态，4 秒内再次点击才真正删除
const clearArmed = ref(false)
let clearTimer: number | undefined

function clearAll() {
  if (!historyItems.value.length) return
  if (!clearArmed.value) {
    clearArmed.value = true
    if (clearTimer) window.clearTimeout(clearTimer)
    clearTimer = window.setTimeout(() => (clearArmed.value = false), 4000)
    return
  }
  conversations.value = []
  clearArmed.value = false
  if (clearTimer) window.clearTimeout(clearTimer)
  closeMenu()
  if (route.path.startsWith('/chat/')) {
    router.replace('/chat')
  }
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    closeMenu()
    clearArmed.value = false
  }
}

onMounted(() => {
  window.addEventListener('click', closeMenu)
  window.addEventListener('scroll', closeMenu, true)
  window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  window.removeEventListener('click', closeMenu)
  window.removeEventListener('scroll', closeMenu, true)
  window.removeEventListener('keydown', onKeydown)
  if (clearTimer) window.clearTimeout(clearTimer)
})
</script>

<template>
  <aside class="sidebar">
    <div class="brand-row">
      <button
        class="collapse-btn"
        type="button"
        aria-label="收起侧栏"
        title="收起侧栏，扩大工作台"
        @click="closeSidebar"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <path d="M9 4v16" />
        </svg>
      </button>
      <router-link to="/chat" class="brand">
        <span class="logo">A</span>
        <span class="brand-name">AgentHub</span>
      </router-link>
    </div>

    <button class="new-chat" type="button" @click="newChat">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 5v14M5 12h14" />
      </svg>
      新建对话
    </button>

    <nav class="nav">
      <section v-for="group in groups" :key="group.label" class="nav-group">
        <p class="group-label">{{ group.label }}</p>
        <router-link
          v-for="item in group.items"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: isActive(item.path) }"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path :d="item.icon" />
          </svg>
          <span>{{ item.label }}</span>
        </router-link>
      </section>
    </nav>

    <div class="history">
      <div class="history-head">
        <span>历史对话</span>
        <span class="history-head-right">
          <button
            v-if="historyItems.length"
            class="history-clear"
            :class="{ armed: clearArmed }"
            type="button"
            @click.stop="clearAll"
          >
            {{ clearArmed ? '确认清空？' : '清空' }}
          </button>
          <span class="muted">{{ conversations.length }}</span>
        </span>
      </div>
      <div v-if="historyItems.length" class="history-list">
        <div
          v-for="item in historyItems"
          :key="item.id"
          class="history-item"
          :class="{ active: route.params.runId === item.id }"
          @contextmenu.prevent.stop="openMenu($event, item.id)"
        >
          <button class="history-open" type="button" @click="openConversation(item.id)">
            <span class="history-title">{{ item.title }}</span>
            <span class="history-meta">
              {{ item.agentName }} · {{ relativeTime(item.updatedAt) }} · {{ item.messages.length }} 条
            </span>
          </button>
          <button
            class="history-remove"
            type="button"
            aria-label="删除对话"
            @click.stop="remove(item.id)"
          >
            ×
          </button>
        </div>
      </div>
      <p v-else class="history-empty">点击“新建对话”开始聊天，历史会出现在这里。</p>
    </div>

    <div v-if="menu" class="history-menu" :style="menuStyle" @click.stop>
      <button type="button" @click="remove(menu.id)">删除对话</button>
    </div>

    <div class="sidebar-foot">
      <span class="mode-dot"></span>
      <span>本地模式</span>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: var(--sidebar-width);
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px 12px;
  background: var(--bg-panel);
  border-right: 1px solid var(--border-color);
  min-height: 0;
  overflow-y: auto;
}

.brand-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 6px;
}

.collapse-btn {
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.collapse-btn:hover {
  background: var(--bg-hover);
  border-color: var(--border-color);
  color: var(--text-main);
}

.collapse-btn svg {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text-main);
}

.brand:hover {
  color: var(--text-main);
}

.logo {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #4d6bfe, #7d5cff);
  color: #fff;
  font-weight: 700;
  font-size: 15px;
}

.brand-name {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.3px;
}

.new-chat {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 38px;
  border-radius: 10px;
  border: 1px dashed var(--border-strong);
  background: transparent;
  color: var(--text-main);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}

.new-chat:hover {
  background: var(--bg-elevated);
  border-color: var(--accent);
}

.new-chat svg {
  width: 15px;
  height: 15px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow-y: auto;
  flex-shrink: 0;
}

.nav-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.group-label {
  margin: 0 0 4px;
  padding: 0 10px;
  font-size: 11px;
  color: var(--text-muted);
  letter-spacing: 0.4px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 34px;
  padding: 0 10px;
  border-radius: 8px;
  color: var(--text-secondary);
  font-size: 13px;
  transition: background 0.15s ease, color 0.15s ease;
}

.nav-item svg {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
  flex-shrink: 0;
}

.nav-item:hover {
  background: var(--bg-elevated);
  color: var(--text-main);
}

.nav-item.active {
  background: var(--accent-soft);
  color: var(--text-main);
}

.nav-item.active svg {
  stroke: var(--accent-hover);
}

.history {
  flex: 1;
  /* 小屏高度下也保留可用的历史区，避免被上方导航压缩为 0 */
  min-height: 180px;
  display: flex;
  flex-direction: column;
  border-top: 1px solid var(--border-color);
  padding-top: 12px;
}

.history-head {
  display: flex;
  justify-content: space-between;
  padding: 0 10px 6px;
  font-size: 11px;
  color: var(--text-muted);
  letter-spacing: 0.4px;
}

.history-head-right {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.history-clear {
  border: none;
  background: transparent;
  padding: 0 2px;
  color: var(--text-muted);
  font-family: inherit;
  font-size: 11px;
  letter-spacing: 0.4px;
  cursor: pointer;
}

.history-clear:hover {
  color: var(--danger);
}

.history-clear.armed {
  color: var(--danger);
  font-weight: 600;
}

.history-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.history-item {
  display: flex;
  align-items: center;
  border-radius: 8px;
}

.history-item:hover,
.history-item.active {
  background: var(--bg-elevated);
}

.history-open {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 7px 10px;
  border: none;
  background: transparent;
  color: inherit;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}

.history-title {
  font-size: 12.5px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-item.active .history-title {
  color: var(--text-main);
}

.history-meta {
  font-size: 11px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-remove {
  visibility: hidden;
  width: 24px;
  height: 24px;
  margin-right: 4px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
}

.history-item:hover .history-remove {
  visibility: visible;
}

.history-remove:hover {
  background: var(--danger-soft);
  color: var(--danger);
}

.history-empty {
  margin: 4px 10px;
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
}

.history-menu {
  position: fixed;
  z-index: 1000;
  min-width: 128px;
  padding: 5px;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background: var(--bg-elevated);
  box-shadow: var(--shadow-pop);
}

.history-menu button {
  width: 100%;
  padding: 7px 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--danger);
  font-family: inherit;
  font-size: 12.5px;
  text-align: left;
  cursor: pointer;
}

.history-menu button:hover {
  background: var(--danger-soft);
}

.sidebar-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 10px 2px;
  border-top: 1px solid var(--border-color);
  font-size: 12px;
  color: var(--text-muted);
}

.mode-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--success);
}

/* 窄屏仍保持并排，只收窄侧栏，保证工作台可同时操作 */
@media (max-width: 768px) {
  .sidebar {
    width: min(220px, 55vw);
    padding: 12px 8px;
  }
}
</style>

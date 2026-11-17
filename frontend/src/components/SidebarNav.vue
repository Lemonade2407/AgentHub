<script setup lang="ts">
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
      {
        label: '账号',
        path: '/settings/profile',
        icon: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM4 21a8 8 0 0 1 16 0',
      },
    ],
  },
]

const route = useRoute()
const router = useRouter()

function isActive(path: string): boolean {
  if (path === '/chat') return route.path.startsWith('/chat')
  if (path === '/agents') return route.path.startsWith('/agents')
  if (path === '/skills') return route.path.startsWith('/skills')
  if (path === '/agent-center') return route.path.startsWith('/agent-center')
  return route.path === path
}

function newChat() {
  router.push('/chat')
  closeSidebar()
}

function openConversation(runId: string) {
  router.push(`/chat/${runId}`)
  closeSidebar()
}

function remove(runId: string) {
  removeConversation(runId)
  if (route.params.runId === runId) {
    router.replace('/chat')
  }
}
</script>

<template>
  <aside class="sidebar">
    <div class="brand-row">
      <router-link to="/chat" class="brand" @click="closeSidebar">
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
          @click="closeSidebar"
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
        <span>最近对话</span>
        <span class="muted">{{ conversations.length }}</span>
      </div>
      <div v-if="conversations.length" class="history-list">
        <div
          v-for="item in conversations"
          :key="item.runId"
          class="history-item"
          :class="{ active: route.params.runId === item.runId }"
        >
          <button class="history-open" type="button" @click="openConversation(item.runId)">
            <span class="history-title">{{ item.title }}</span>
            <span class="history-meta">
              {{ item.agentName }} · {{ relativeTime(item.createdAt) }}
            </span>
          </button>
          <button
            class="history-remove"
            type="button"
            aria-label="删除会话"
            @click.stop="remove(item.runId)"
          >
            ×
          </button>
        </div>
      </div>
      <p v-else class="history-empty">发送第一条消息后，会话会出现在这里。</p>
    </div>

    <div class="sidebar-foot">
      <span class="mode-dot"></span>
      <span>本地模式</span>
      <router-link to="/settings/profile" class="foot-link" @click="closeSidebar">账号</router-link>
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
}

.brand-row {
  padding: 0 6px;
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
  min-height: 0;
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

.foot-link {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-muted);
}

.foot-link:hover {
  color: var(--text-main);
}

@media (max-width: 1024px) {
  .sidebar {
    position: fixed;
    left: 0;
    top: 0;
    bottom: 0;
    z-index: 50;
    transform: translateX(-100%);
    transition: transform 0.2s ease;
    box-shadow: var(--shadow-pop);
  }

  .sidebar-open .sidebar {
    transform: translateX(0);
  }
}

@media (max-width: 768px) {
  .sidebar {
    padding-bottom: 64px;
  }
}
</style>

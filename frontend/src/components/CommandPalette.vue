<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/http'
import { closePalette, ui } from '../stores/ui'
import type { Agent, Page } from '../types/api'
import type { Skill, ToolDefinition } from '../types/skill'

interface PaletteItem {
  id: string
  group: string
  label: string
  hint?: string
  to: string
}

const staticItems: PaletteItem[] = [
  { id: 'page-chat', group: '页面', label: '工作台', hint: '新建对话', to: '/chat' },
  { id: 'page-agents', group: '页面', label: 'Agents', hint: 'Agent 列表', to: '/agents' },
  { id: 'page-skills', group: '页面', label: 'Skills Center', hint: '我的 / 广场', to: '/skills' },
  { id: 'page-center', group: '页面', label: 'Agent Center', hint: '发布与安装', to: '/agent-center' },
  { id: 'page-mcp', group: '页面', label: 'MCP Hub', hint: 'Server 与工具', to: '/mcp' },
  { id: 'page-models', group: '页面', label: '模型 API', hint: '模型接入设置', to: '/settings/models' },
  { id: 'action-new-agent', group: '动作', label: '新建 Agent', to: '/agents/new' },
  { id: 'action-new-skill', group: '动作', label: '新建 Skill', to: '/skills/new' },
]

const router = useRouter()
const query = ref('')
const activeIndex = ref(0)
const inputRef = ref<HTMLInputElement | null>(null)
const dynamicItems = ref<PaletteItem[]>([])
const loading = ref(false)
let loaded = false

const results = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  const all = [...staticItems, ...dynamicItems.value]
  if (!keyword) return all.slice(0, 24)
  return all
    .filter((item) => `${item.label} ${item.hint ?? ''}`.toLowerCase().includes(keyword))
    .slice(0, 24)
})

const activeItem = computed(() => results.value[activeIndex.value])

function groupStart(index: number): boolean {
  if (index === 0) return true
  return results.value[index - 1].group !== results.value[index].group
}

async function loadDynamic() {
  if (loaded) return
  loaded = true
  loading.value = true
  const [agents, skills, tools] = await Promise.allSettled([
    api.get<Page<Agent>>('/api/agents?page_size=100'),
    api.get<Page<Skill>>('/api/skills?page_size=100'),
    api.get<Page<ToolDefinition>>('/api/mcp/tools?page_size=100'),
  ])
  const items: PaletteItem[] = []
  if (agents.status === 'fulfilled') {
    for (const agent of agents.value.items) {
      items.push({
        id: `agent-${agent.id}`,
        group: 'Agents',
        label: agent.name,
        hint: agent.model || '对话时选择模型',
        to: `/agents/${agent.id}`,
      })
    }
  }
  if (skills.status === 'fulfilled') {
    for (const skill of skills.value.items) {
      items.push({
        id: `skill-${skill.id}`,
        group: 'Skills',
        label: skill.name,
        hint: `${skill.slug} · v${skill.version}`,
        to: `/skills/${skill.id}`,
      })
    }
  }
  if (tools.status === 'fulfilled') {
    for (const tool of tools.value.items) {
      items.push({
        id: `tool-${tool.id}`,
        group: '工具',
        label: tool.qualified_name,
        hint: tool.server_name,
        to: '/mcp',
      })
    }
  }
  dynamicItems.value = items
  loading.value = false
}

function choose(item?: PaletteItem) {
  const target = item ?? activeItem.value
  if (!target) return
  router.push(target.to)
  closePalette()
}

function move(delta: number) {
  const total = results.value.length
  if (!total) return
  activeIndex.value = (activeIndex.value + delta + total) % total
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    move(1)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    move(-1)
  } else if (event.key === 'Enter') {
    event.preventDefault()
    choose()
  } else if (event.key === 'Escape') {
    event.preventDefault()
    closePalette()
  }
}

watch(
  () => ui.paletteOpen,
  async (open) => {
    if (open) {
      query.value = ''
      activeIndex.value = 0
      await nextTick()
      inputRef.value?.focus()
      void loadDynamic()
    }
  },
)

watch(query, () => {
  activeIndex.value = 0
})
</script>

<template>
  <Teleport to="body">
    <div v-if="ui.paletteOpen" class="palette-overlay" @click.self="closePalette">
      <div class="palette" role="dialog" aria-label="命令面板">
        <div class="palette-input">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.2-3.2" />
          </svg>
          <input
            ref="inputRef"
            v-model="query"
            type="text"
            placeholder="搜索 Agent / Skill / 工具 / 页面…"
            @keydown="onKeydown"
          />
          <kbd>ESC</kbd>
        </div>

        <div class="palette-body">
          <p v-if="loading && !results.length" class="palette-tip">加载资源中…</p>
          <template v-for="(item, index) in results" :key="item.id">
            <p v-if="groupStart(index)" class="palette-group">{{ item.group }}</p>
            <button
              class="palette-item"
              :class="{ active: index === activeIndex }"
              type="button"
              @mouseenter="activeIndex = index"
              @click="choose(item)"
            >
              <span class="item-label">{{ item.label }}</span>
              <span v-if="item.hint" class="item-hint">{{ item.hint }}</span>
            </button>
          </template>
          <p v-if="!loading && !results.length" class="palette-tip">没有匹配结果</p>
        </div>

        <div class="palette-foot">
          <span><kbd>↑</kbd><kbd>↓</kbd> 选择</span>
          <span><kbd>Enter</kbd> 打开</span>
          <span class="muted">跨资源搜索</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.palette-overlay {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 12vh;
  background: rgba(5, 7, 10, 0.7);
  backdrop-filter: blur(3px);
}

.palette {
  width: min(620px, calc(100vw - 32px));
  max-height: 70vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-pop);
  overflow: hidden;
}

.palette-input {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
}

.palette-input svg {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: var(--text-muted);
  stroke-width: 1.8;
}

.palette-input input {
  flex: 1;
  border: none;
  background: transparent;
  padding: 0;
  font-size: 14px;
}

kbd {
  padding: 0 5px;
  border: 1px solid var(--border-color);
  border-radius: 5px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 16px;
}

.palette-body {
  flex: 1;
  overflow-y: auto;
  padding: 6px 8px 10px;
}

.palette-group {
  margin: 8px 8px 4px;
  font-size: 11px;
  color: var(--text-muted);
  letter-spacing: 0.4px;
}

.palette-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  font-family: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}

.palette-item.active {
  background: var(--accent-soft);
  color: var(--text-main);
}

.item-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-hint {
  font-size: 11.5px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 45%;
}

.palette-tip {
  margin: 16px;
  text-align: center;
  font-size: 12.5px;
  color: var(--text-muted);
}

.palette-foot {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 8px 16px;
  border-top: 1px solid var(--border-color);
  font-size: 11px;
  color: var(--text-muted);
}

.palette-foot .muted {
  margin-left: auto;
}
</style>

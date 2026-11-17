import { ref, watch } from 'vue'

export interface Conversation {
  runId: string
  agentId: number
  agentName: string
  model: string
  title: string
  createdAt: string
  status?: string
}

const STORAGE_KEY = 'agenthub.conversations.v1'
const MAX_ITEMS = 40

function load(): Conversation[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (item): item is Conversation =>
        item != null && typeof item.runId === 'string' && typeof item.title === 'string',
    )
  } catch {
    return []
  }
}

/** 左侧任务栏的“最近对话”，仅保存在本地浏览器（后端暂无会话列表接口）。 */
export const conversations = ref<Conversation[]>(load())

watch(
  conversations,
  (value) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(value.slice(0, MAX_ITEMS)))
    } catch {
      // 隐私模式等场景下 localStorage 不可写，忽略即可
    }
  },
  { deep: true },
)

export function upsertConversation(item: Conversation): void {
  const index = conversations.value.findIndex((entry) => entry.runId === item.runId)
  if (index >= 0) {
    conversations.value[index] = { ...conversations.value[index], ...item }
    return
  }
  conversations.value.unshift(item)
  conversations.value = conversations.value.slice(0, MAX_ITEMS)
}

export function updateConversation(runId: string, patch: Partial<Conversation>): void {
  const index = conversations.value.findIndex((entry) => entry.runId === runId)
  if (index >= 0) {
    conversations.value[index] = { ...conversations.value[index], ...patch }
  }
}

export function removeConversation(runId: string): void {
  conversations.value = conversations.value.filter((entry) => entry.runId !== runId)
}

import { ref, watch } from 'vue'

export interface ChatMessage {
  runId: string
  userText: string
  assistantText: string | null
  status?: string
  createdAt: string
}

export interface Conversation {
  id: string
  title: string
  agentId: number
  agentName: string
  model: string
  createdAt: string
  updatedAt: string
  messages: ChatMessage[]
}

const STORAGE_KEY = 'agenthub.conversations.v2'
const LEGACY_KEY = 'agenthub.conversations.v1'
const MAX_ITEMS = 60
const MAX_MESSAGES = 100
const MAX_TITLE_CHARS = 26

/** 把首条提示词整理成一句简短的话，作为历史对话标题。 */
function shortenSentence(text: string): string {
  const oneLine = text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/[#>*_`~]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (!oneLine) return ''
  return oneLine.length > MAX_TITLE_CHARS
    ? `${oneLine.slice(0, MAX_TITLE_CHARS)}…`
    : oneLine
}

export function deriveTitle(conversation: Conversation): string {
  const firstPrompt = conversation.messages.find((message) => message.userText.trim())
    ?.userText
  return shortenSentence(firstPrompt ?? conversation.title) || '新对话'
}

function withDerivedTitle(conversation: Conversation): Conversation {
  return conversation.messages.length
    ? { ...conversation, title: deriveTitle(conversation) }
    : conversation
}

function isConversation(value: unknown): value is Conversation {
  if (value == null || typeof value !== 'object') return false
  const item = value as Partial<Conversation>
  return (
    typeof item.id === 'string' &&
    typeof item.title === 'string' &&
    Array.isArray(item.messages)
  )
}

/** 旧版“最近对话”按 Run 存储，这里迁移为单消息会话，保留历史记录。 */
function migrateLegacy(): Conversation[] {
  try {
    const raw = localStorage.getItem(LEGACY_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((item) => item != null && typeof item.runId === 'string')
      .map((item) => {
        const createdAt = String(item.createdAt ?? new Date().toISOString())
        return {
          id: `c_legacy_${item.runId}`,
          title: String(item.title ?? '未命名对话'),
          agentId: Number(item.agentId) || 0,
          agentName: String(item.agentName ?? 'Agent'),
          model: String(item.model ?? ''),
          createdAt,
          updatedAt: createdAt,
          messages: [
            {
              runId: item.runId,
              userText: String(item.title ?? ''),
              assistantText: null,
              status: item.status ? String(item.status) : undefined,
              createdAt,
            },
          ],
        }
      })
  } catch {
    return []
  }
}

function load(): Conversation[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) {
        return (parsed.filter(isConversation) as Conversation[]).map(withDerivedTitle)
      }
    }
    return migrateLegacy().map(withDerivedTitle)
  } catch {
    return []
  }
}

/** 历史对话保存在本地浏览器（后端暂无会话列表接口）。 */
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

function newId(): string {
  return `c_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`
}

export function createConversation(input: {
  agentId: number
  agentName: string
  model: string
  title: string
}): Conversation {
  const now = new Date().toISOString()
  const conversation: Conversation = {
    id: newId(),
    title: input.title.slice(0, 48),
    agentId: input.agentId,
    agentName: input.agentName,
    model: input.model,
    createdAt: now,
    updatedAt: now,
    messages: [],
  }
  conversations.value = [conversation, ...conversations.value].slice(0, MAX_ITEMS)
  return conversation
}

export function getConversation(id: string): Conversation | undefined {
  return conversations.value.find((entry) => entry.id === id)
}

export function findConversationByRunId(runId: string): Conversation | undefined {
  return conversations.value.find((entry) =>
    entry.messages.some((message) => message.runId === runId),
  )
}

export function appendMessage(conversationId: string, message: ChatMessage): void {
  const conversation = getConversation(conversationId)
  if (!conversation) return
  conversation.messages = [...conversation.messages, message].slice(-MAX_MESSAGES)
  conversation.updatedAt = message.createdAt
  conversation.title = deriveTitle(conversation)
}

export function updateMessage(
  conversationId: string,
  runId: string,
  patch: Partial<ChatMessage>,
): void {
  const conversation = getConversation(conversationId)
  if (!conversation) return
  const index = conversation.messages.findIndex((message) => message.runId === runId)
  if (index < 0) return
  conversation.messages[index] = { ...conversation.messages[index], ...patch }
  conversation.title = deriveTitle(conversation)
}

export function updateConversation(
  id: string,
  patch: Partial<Omit<Conversation, 'id' | 'messages'>>,
): void {
  const conversation = getConversation(id)
  if (!conversation) return
  Object.assign(conversation, patch)
}

export function removeConversation(id: string): void {
  conversations.value = conversations.value.filter((entry) => entry.id !== id)
}

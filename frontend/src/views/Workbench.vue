<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errorMessage } from '../api/http'
import ChatComposer from '../components/ChatComposer.vue'
import MarkdownMessage from '../components/MarkdownMessage.vue'
import ProcessList from '../components/ProcessList.vue'
import TracePanel from '../components/TracePanel.vue'
import {
  appendMessage,
  createConversation,
  findConversationByRunId,
  getConversation,
  removeConversation,
  updateConversation,
  updateMessage,
  type ChatMessage,
} from '../stores/conversations'
import type { Agent, Page, RunRead, StepRead, TraceEvent } from '../types/api'

const route = useRoute()
const router = useRouter()

const agents = ref<Agent[]>([])
const agentId = ref<number | null>(null)
// 模型是“本次对话”的选择，不再写回 Agent
const selectedModel = ref('')
const input = ref('')
const maxSteps = ref<number | null>(null)
const notice = ref('')

const running = ref(false)
const loadingRun = ref(false)
const events = ref<TraceEvent[]>([])
const runInfo = ref<RunRead | null>(null)
const finalOutput = ref<string | null>(null)
const finalError = ref<string | null>(null)
const runStatus = ref<'running' | 'success' | 'partial' | 'failed' | 'cancelled' | null>(null)
const activeRunId = ref<string | null>(null)
const error = ref('')

const scrollRef = ref<HTMLElement | null>(null)
const composerRef = ref<InstanceType<typeof ChatComposer> | null>(null)

let es: EventSource | null = null
let noticeTimer: number | undefined
const seenEvents = new Set<string>()

const wideQuery = window.matchMedia('(min-width: 1281px)')
const traceOpen = ref(wideQuery.matches)

const routeKey = computed(() => {
  const value = route.params.runId
  return Array.isArray(value) ? value[0] : value
})

const conversation = computed(() => {
  const key = routeKey.value
  if (!key || !key.startsWith('c_')) return null
  return getConversation(key) ?? null
})
const hasRun = computed(() => !!conversation.value)
const messages = computed(() => conversation.value?.messages ?? [])
const memoryTurns = computed(() =>
  messages.value.reduce(
    (count, message) =>
      count +
      (message.userText.trim() ? 1 : 0) +
      (message.assistantText?.trim() ? 1 : 0),
    0,
  ),
)
const showMemoryHint = computed(() => memoryTurns.value > 20)
const selectedAgent = computed(() => agents.value.find((agent) => agent.id === agentId.value) ?? null)
const isRunning = computed(() => runStatus.value === 'running' || running.value)
const showModelFix = computed(() =>
  /鉴权|auth|401|模型不存在|MODEL_NOT_AVAILABLE|MODEL_API|LLM_AUTH|模型.*失败/i.test(
    `${finalError.value ?? ''} ${error.value}`,
  ),
)

const SSE_EVENT_NAMES = [
  'run_started',
  'llm_started',
  'llm_finished',
  'tool_candidates',
  'skill_injected',
  'skill_tool_missing',
  'tool_call_started',
  'tool_call_finished',
  'state_updated',
  'run_finished',
  'run_failed',
] as const

function showNotice(text: string) {
  notice.value = text
  if (noticeTimer) window.clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => (notice.value = ''), 3200)
}

function scrollToBottom() {
  const element = scrollRef.value
  if (!element) return
  element.scrollTop = element.scrollHeight
}

// ---------- 数据加载 ----------

async function loadAgents() {
  try {
    const data = await api.get<Page<Agent>>('/api/agents?page_size=100')
    agents.value = data.items.filter((agent) => agent.enabled)
    if (!agents.value.some((agent) => agent.id === agentId.value)) {
      const stored = Number(localStorage.getItem('agenthub.lastAgent'))
      agentId.value =
        agents.value.find((agent) => agent.id === stored)?.id ?? agents.value[0]?.id ?? null
    }
    syncSelectedModel()
  } catch (e) {
    error.value = errorMessage(e, 'Agent 列表加载失败')
  }
}

function stepToEvent(step: StepRead): TraceEvent {
  return {
    run_id: step.run_id,
    step_no: step.step_no,
    event_type: step.event_type,
    status: step.status,
    node: step.node,
    tool: step.tool,
    duration_ms: step.duration_ms,
    data: step.payload,
    timestamp: step.created_at,
  }
}

function applyRunStatus(run: RunRead) {
  if (run.status === 'SUCCESS' || run.status === 'PARTIAL') {
    runStatus.value = run.status === 'PARTIAL' ? 'partial' : 'success'
  } else if (run.status === 'FAILED') {
    runStatus.value = 'failed'
  } else if (run.status === 'CANCELLED') {
    runStatus.value = 'cancelled'
  } else {
    runStatus.value = 'running'
  }
}

function statusText(status?: string | null): string {
  const value = (status ?? '').toUpperCase()
  if (value === 'SUCCESS') return '成功'
  if (value === 'PARTIAL') return '部分完成'
  if (value === 'FAILED') return '失败'
  if (value === 'CANCELLED') return '已取消'
  if (value === 'RUNNING' || value === 'PENDING') return '执行中'
  return '已结束'
}

function statusClass(status?: string | null): string {
  const value = (status ?? '').toLowerCase()
  if (value === 'pending') return 'running'
  return ['success', 'partial', 'failed', 'cancelled', 'running'].includes(value) ? value : ''
}

async function loadConversation(id: string) {
  closeStream()
  loadingRun.value = true
  error.value = ''
  events.value = []
  runInfo.value = null
  finalOutput.value = null
  finalError.value = null
  runStatus.value = null
  activeRunId.value = null
  seenEvents.clear()

  const conv = getConversation(id)
  if (!conv) {
    loadingRun.value = false
    void router.replace('/chat')
    return
  }

  agentId.value = conv.agentId
  if (conv.model) selectedModel.value = conv.model

  const entries = conv.messages.slice(-30)
  try {
    // 用后端 Run 补齐本地可能缺失的回答与状态（例如旧版本迁移的会话）
    const runs = await Promise.all(
      entries.map((message) =>
        api.get<RunRead>(`/api/runs/${message.runId}`).catch(() => null),
      ),
    )
    runs.forEach((run, index) => {
      if (!run) return
      const message = entries[index]
      updateMessage(id, message.runId, {
        userText: run.input || message.userText,
        assistantText: run.output ?? message.assistantText,
        status: run.status,
      })
    })

    const last = entries[entries.length - 1]
    if (last) {
      activeRunId.value = last.runId
      const lastRun = runs[runs.length - 1]
      if (lastRun) {
        runInfo.value = lastRun
        applyRunStatus(lastRun)
        finalOutput.value = lastRun.output ?? null
        finalError.value = lastRun.error_message ?? null
      }

      const steps = await api
        .get<Page<StepRead>>(`/api/runs/${last.runId}/steps?page_size=500`)
        .catch(() => null)
      if (steps) {
        events.value = steps.items.map(stepToEvent)
        for (const event of events.value) {
          seenEvents.add(`${event.event_type}|${event.step_no}|${event.timestamp}`)
        }
      }

      if (lastRun && (lastRun.status === 'PENDING' || lastRun.status === 'RUNNING')) {
        openStream(last.runId)
      }
    }

    if (!agents.value.some((agent) => agent.id === conv.agentId)) {
      try {
        const agent = await api.get<Agent>(`/api/agents/${conv.agentId}`)
        agents.value.unshift(agent)
      } catch {
        // Agent 可能已被删除，历史会话仍可查看
      }
    }
  } catch (e) {
    error.value = errorMessage(e, '会话加载失败')
  } finally {
    loadingRun.value = false
    void nextTick(scrollToBottom)
  }
}

async function refreshRun(runId: string) {
  const conv = conversation.value
  try {
    const run = await api.get<RunRead>(`/api/runs/${runId}`)
    if (runId === activeRunId.value) {
      runInfo.value = run
      applyRunStatus(run)
      if (run.output) finalOutput.value = run.output
      if (run.error_message) finalError.value = run.error_message
    }
    if (conv) {
      const patch: Partial<ChatMessage> = { status: run.status }
      if (run.output) patch.assistantText = run.output
      updateMessage(conv.id, runId, patch)
    }
  } catch {
    // 终态事件已提供足够信息，刷新失败不影响展示
  }
}

function resetSession() {
  closeStream()
  events.value = []
  runInfo.value = null
  finalOutput.value = null
  finalError.value = null
  runStatus.value = null
  activeRunId.value = null
  error.value = ''
  seenEvents.clear()
}

// ---------- SSE ----------

function handleEvent(payload: MessageEvent) {
  let parsed: TraceEvent
  try {
    parsed = JSON.parse(payload.data)
  } catch {
    return
  }
  const key = `${parsed.event_type}|${parsed.step_no}|${parsed.timestamp}`
  if (seenEvents.has(key)) return
  seenEvents.add(key)
  events.value.push(parsed)

  if (parsed.event_type === 'RUN_FINISHED') {
    const stopReason = (parsed.data?.stop_reason as string) ?? ''
    finalOutput.value = (parsed.data?.output as string) ?? null
    runStatus.value = stopReason === 'MAX_STEPS' ? 'partial' : 'success'
    saveActiveMessage(finalOutput.value, runStatus.value === 'partial' ? 'PARTIAL' : 'SUCCESS')
    closeStream()
    if (activeRunId.value) void refreshRun(activeRunId.value)
  } else if (parsed.event_type === 'RUN_FAILED') {
    const stopReason = (parsed.data?.stop_reason as string) ?? ''
    finalOutput.value = (parsed.data?.partial_output as string) ?? null
    finalError.value =
      (parsed.data?.error_message as string) ?? stopReason ?? '执行失败'
    runStatus.value = stopReason === 'CANCELLED' ? 'cancelled' : 'failed'
    saveActiveMessage(finalOutput.value, stopReason === 'CANCELLED' ? 'CANCELLED' : 'FAILED')
    closeStream()
    if (activeRunId.value) void refreshRun(activeRunId.value)
  }
}

/** 把当前 Run 的最终回答写回所属会话，切换会话后仍可看到。 */
function saveActiveMessage(assistantText: string | null, status: string) {
  const conv = conversation.value
  const runId = activeRunId.value
  if (!conv || !runId) return
  updateMessage(conv.id, runId, { assistantText, status })
}

function openStream(runId: string) {
  closeStream()
  running.value = true
  runStatus.value = 'running'
  es = new EventSource(`/api/runs/${runId}/events`)
  for (const name of SSE_EVENT_NAMES) {
    es.addEventListener(name, handleEvent as EventListener)
  }
  es.onerror = () => {
    closeStream()
    void refreshRun(runId)
  }
}

function closeStream() {
  if (es) {
    es.close()
    es = null
  }
  running.value = false
}

// ---------- 交互 ----------

function syncSelectedModel() {
  // 模型不再绑定在 Agent 上，沿用用户在对话窗口上一次的选择
  selectedModel.value = localStorage.getItem('agenthub.lastModel') ?? ''
}

function onAgentChange(id: number) {
  const changed = agentId.value != null && agentId.value !== id
  agentId.value = id
  localStorage.setItem('agenthub.lastAgent', String(id))
  syncSelectedModel()
  // 切换 Agent 意味着换一个上下文：自动回到新建对话，不把新 Agent 的回复写入当前会话
  if (changed && hasRun.value) {
    showNotice('已切换 Agent，开始新对话')
    void router.push('/chat')
    resetSession()
  }
}

function onModelChange(model: string) {
  selectedModel.value = model
  localStorage.setItem('agenthub.lastModel', model)
  showNotice(`本次对话将使用模型：${model}`)
}

function buildHistory(items: ChatMessage[]) {
  const turns: { role: 'user' | 'assistant'; content: string }[] = []
  for (const message of items) {
    if (message.userText.trim()) {
      turns.push({ role: 'user', content: message.userText })
    }
    if (message.assistantText?.trim()) {
      turns.push({ role: 'assistant', content: message.assistantText })
    }
  }
  return turns.slice(-20)
}

async function send() {
  if (agentId.value == null) {
    error.value = '请先选择 Agent'
    return
  }
  const text = input.value.trim()
  if (!text || isRunning.value) return
  const model = selectedModel.value || ''
  if (!model) {
    error.value = '请先选择模型'
    return
  }

  error.value = ''
  finalOutput.value = null
  finalError.value = null
  events.value = []
  seenEvents.clear()
  runStatus.value = 'running'
  running.value = true
  const sent = text
  input.value = ''

  let createdId: string | null = null
  try {
    const existing = conversation.value
    const target =
      existing ??
      createConversation({
        agentId: agentId.value,
        agentName: selectedAgent.value?.name ?? `Agent ${agentId.value}`,
        model,
        title: sent,
      })
    if (!existing) {
      createdId = target.id
    } else {
      updateConversation(target.id, {
        agentName: selectedAgent.value?.name ?? target.agentName,
        model,
        updatedAt: new Date().toISOString(),
      })
    }

    const run = await api.post<RunRead>(`/api/agents/${agentId.value}/runs`, {
      input: sent,
      max_steps: maxSteps.value ?? undefined,
      model,
      history: existing ? buildHistory(existing.messages) : [],
    })
    runInfo.value = run
    activeRunId.value = run.id
    appendMessage(target.id, {
      runId: run.id,
      userText: sent,
      assistantText: null,
      status: run.status,
      createdAt: new Date().toISOString(),
    })
    if (routeKey.value !== target.id) {
      await router.push(`/chat/${target.id}`)
    }
    openStream(run.id)
  } catch (e) {
    if (createdId) removeConversation(createdId)
    running.value = false
    runStatus.value = null
    error.value = errorMessage(e, '创建任务失败')
    input.value = sent
  }
}

function onWideChange(event: MediaQueryListEvent) {
  if (!event.matches) traceOpen.value = false
}

watch(routeKey, (key, previous) => {
  if (key === previous) return
  if (!key) {
    resetSession()
    return
  }

  const convId = key.startsWith('c_') ? key : findConversationByRunId(key)?.id ?? null
  if (!convId) {
    error.value = '会话不存在或已被删除'
    void router.replace('/chat')
    return
  }
  if (convId !== key) {
    void router.replace(`/chat/${convId}`)
    return
  }

  // 刚在当前会话发起的新 Run：消息已追加，无需重新加载
  const conv = getConversation(convId)
  if (
    activeRunId.value &&
    conv?.messages.some((message) => message.runId === activeRunId.value)
  ) {
    return
  }
  void loadConversation(convId)
})

watch(
  () => [events.value.length, finalOutput.value, runStatus.value],
  () => {
    void nextTick(scrollToBottom)
  },
)

onMounted(async () => {
  wideQuery.addEventListener('change', onWideChange)
  await loadAgents()

  const key = routeKey.value
  if (key) {
    const convId = key.startsWith('c_') ? key : findConversationByRunId(key)?.id ?? null
    if (!convId) {
      await router.replace('/chat')
    } else if (convId !== key) {
      await router.replace(`/chat/${convId}`)
    } else {
      await loadConversation(convId)
    }
    return
  }

  const queryAgent = Number(route.query.agent)
  if (queryAgent && agents.value.some((agent) => agent.id === queryAgent)) {
    agentId.value = queryAgent
  }
  void nextTick(() => composerRef.value?.focus())
})

onUnmounted(() => {
  closeStream()
  wideQuery.removeEventListener('change', onWideChange)
  if (noticeTimer) window.clearTimeout(noticeTimer)
})
</script>

<template>
  <div class="workbench">
    <section class="chat-col">
      <header class="chat-head">
        <div class="head-info">
          <span class="head-agent">{{ selectedAgent?.name ?? '工作台' }}</span>
          <span v-if="selectedAgent" class="head-model">
            {{ selectedModel || '对话时选择模型' }}
          </span>
        </div>
        <div class="head-actions">
          <button class="btn btn-sm" type="button" @click="traceOpen = !traceOpen">
            {{ traceOpen ? '收起执行过程' : '执行过程' }}
          </button>
        </div>
      </header>

      <!-- 空态：对话优先的起始页 -->
      <div v-if="!hasRun && !isRunning" class="empty-stage">
        <div class="hero">
          <h1>想让 Agent 做什么？</h1>

          <p v-if="!agents.length" class="hero-empty">
            还没有 Agent，先
            <router-link to="/agents/new">新建一个</router-link>
            再开始对话
          </p>
        </div>

        <ChatComposer
          ref="composerRef"
          :agents="agents"
          :agent-id="agentId"
          :model="selectedModel"
          :input="input"
          :max-steps="maxSteps"
          :running="isRunning"
          @update:agent-id="onAgentChange"
          @update:input="input = $event"
          @update:max-steps="maxSteps = $event"
          @change-model="onModelChange"
          @send="send"
        />

        <p v-if="error" class="error-box composer-error">{{ error }}</p>
      </div>

      <!-- 对话态 -->
      <template v-else>
        <div ref="scrollRef" class="chat-scroll">
          <div class="thread">
            <template v-for="message in messages" :key="message.runId">
              <div class="msg user">
                <div class="bubble">{{ message.userText }}</div>
              </div>

              <div class="msg assistant">
                <div class="assistant-line">
                  <span class="assistant-avatar">A</span>
                  <span class="assistant-name">
                    {{ conversation?.agentName ?? selectedAgent?.name ?? 'Agent' }}
                  </span>
                  <span class="assistant-run">{{ message.runId }}</span>
                </div>

                <template v-if="message.runId === activeRunId">
                  <div v-if="loadingRun" class="thinking">
                    <span class="pulse"></span>加载会话…
                  </div>

                  <template v-else>
                    <div v-if="isRunning && !events.length" class="thinking">
                      <span class="pulse"></span>Agent 正在思考…
                    </div>

                    <ProcessList :events="events" />

                    <MarkdownMessage v-if="finalOutput" class="answer" :content="finalOutput" />

                    <div v-if="finalError" class="error-box answer-error">
                      <span>{{ finalError }}</span>
                      <router-link v-if="showModelFix" to="/settings/models">去配置模型</router-link>
                    </div>

                    <div v-if="error" class="error-box answer-error">{{ error }}</div>

                    <div v-if="runInfo && !isRunning" class="run-meta">
                      <span class="badge" :class="runStatus ?? ''">
                        {{ statusText(runStatus) }}
                      </span>
                      <span>{{ runInfo.llm_calls }} 次 LLM</span>
                      <span>{{ runInfo.tool_calls }} 次工具</span>
                      <span>{{ runInfo.step_count }} 步</span>
                    </div>
                  </template>
                </template>

                <template v-else>
                  <MarkdownMessage
                    v-if="message.assistantText"
                    class="answer"
                    :content="message.assistantText"
                  />
                  <div v-else class="thinking">该轮回答未保存到本地</div>
                  <div class="run-meta">
                    <span class="badge" :class="statusClass(message.status)">
                      {{ statusText(message.status) }}
                    </span>
                  </div>
                </template>
              </div>
            </template>
          </div>
        </div>

        <div class="composer-wrap">
          <ChatComposer
            ref="composerRef"
            :agents="agents"
            :agent-id="agentId"
            :model="selectedModel"
            :input="input"
            :max-steps="maxSteps"
            :running="isRunning"
            @update:agent-id="onAgentChange"
            @update:input="input = $event"
            @update:max-steps="maxSteps = $event"
            @change-model="onModelChange"
            @send="send"
          />
          <p class="composer-tip">执行过程可在右侧面板对照查看，全程不刷新页面。</p>
          <p v-if="showMemoryHint" class="memory-hint">
            对话记忆已超过 20 条，建议打开新的对话。
          </p>
        </div>
      </template>

      <Transition name="toast">
        <div v-if="notice" class="toast">{{ notice }}</div>
      </Transition>
    </section>

    <TracePanel
      v-if="traceOpen"
      :run="runInfo"
      :events="events"
      :running="isRunning"
      @close="traceOpen = false"
    />
  </div>
</template>

<style scoped>
.workbench {
  display: flex;
  height: 100%;
  min-height: 0;
}

.chat-col {
  position: relative;
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.chat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  height: 52px;
  flex-shrink: 0;
  padding: 0 24px;
  border-bottom: 1px solid var(--border-color);
}

.head-info {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.head-agent {
  font-size: 13.5px;
  font-weight: 600;
}

.head-model {
  font-size: 11.5px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.empty-stage {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 22px;
  padding: 40px 24px;
}

.hero {
  width: min(760px, 100%);
  text-align: center;
}

.hero h1 {
  margin: 0 0 8px;
  font-size: 24px;
  font-weight: 600;
  letter-spacing: 0.2px;
}

.hero-empty {
  margin-top: 16px;
  font-size: 12.5px;
  color: var(--text-secondary);
}

.empty-stage :deep(.composer) {
  width: min(760px, 100%);
}

.composer-error {
  width: min(760px, 100%);
}

.chat-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 26px 24px 8px;
}

.thread {
  width: min(760px, 100%);
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 22px;
}

.msg.user {
  display: flex;
  justify-content: flex-end;
}

.bubble {
  max-width: 82%;
  padding: 10px 14px;
  border-radius: 16px 16px 4px 16px;
  background: var(--accent-soft);
  border: 1px solid rgba(77, 107, 254, 0.32);
  color: var(--text-main);
  font-size: 13.5px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.msg.assistant {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.assistant-line {
  display: flex;
  align-items: center;
  gap: 8px;
}

.assistant-avatar {
  width: 24px;
  height: 24px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  color: var(--accent-hover);
  font-size: 12px;
  font-weight: 600;
}

.assistant-name {
  font-size: 12.5px;
  font-weight: 600;
}

.assistant-run {
  font-size: 10.5px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.thinking {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--text-muted);
}

.pulse {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
  animation: pulse 1.2s ease-in-out infinite;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 0.3;
    transform: scale(0.8);
  }
  50% {
    opacity: 1;
    transform: scale(1);
  }
}

.answer {
  font-size: 13.5px;
  line-height: 1.8;
  color: var(--text-main);
  white-space: pre-wrap;
  word-break: break-word;
}

.answer-error {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.run-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  font-size: 11.5px;
  color: var(--text-muted);
}

.composer-wrap {
  flex-shrink: 0;
  padding: 8px 24px 16px;
}

.composer-wrap :deep(.composer) {
  width: min(760px, 100%);
  margin: 0 auto;
}

.composer-tip {
  width: min(760px, 100%);
  margin: 6px auto 0;
  font-size: 10.5px;
  color: var(--text-muted);
  text-align: center;
}

.memory-hint {
  width: min(760px, 100%);
  margin: 4px auto 0;
  font-size: 11px;
  color: var(--warn);
  text-align: center;
}

.toast {
  position: absolute;
  left: 50%;
  bottom: 96px;
  transform: translateX(-50%);
  padding: 7px 14px;
  border-radius: 999px;
  border: 1px solid var(--border-strong);
  background: var(--bg-elevated);
  color: var(--text-main);
  font-size: 12px;
  box-shadow: var(--shadow-pop);
  z-index: 20;
}

.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translate(-50%, 6px);
}

@media (max-width: 768px) {
  .chat-head {
    padding: 0 14px;
  }

  .chat-scroll {
    padding: 18px 14px 6px;
  }

  .composer-wrap {
    padding: 6px 12px 12px;
  }

  .empty-stage {
    padding: 24px 14px;
  }

  .hero h1 {
    font-size: 20px;
  }
}
</style>

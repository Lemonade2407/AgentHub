<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errorMessage } from '../api/http'
import ChatComposer from '../components/ChatComposer.vue'
import ProcessList from '../components/ProcessList.vue'
import TracePanel from '../components/TracePanel.vue'
import { upsertConversation, updateConversation } from '../stores/conversations'
import type { Agent, Page, RunRead, StepRead, TraceEvent } from '../types/api'

const route = useRoute()
const router = useRouter()

const agents = ref<Agent[]>([])
const agentId = ref<number | null>(null)
const input = ref('')
const maxSteps = ref<number | null>(null)
const userText = ref('')
const notice = ref('')

const running = ref(false)
const loadingRun = ref(false)
const events = ref<TraceEvent[]>([])
const runInfo = ref<RunRead | null>(null)
const finalOutput = ref<string | null>(null)
const finalError = ref<string | null>(null)
const runStatus = ref<'running' | 'success' | 'partial' | 'failed' | 'cancelled' | null>(null)
const error = ref('')

const scrollRef = ref<HTMLElement | null>(null)
const composerRef = ref<InstanceType<typeof ChatComposer> | null>(null)

let es: EventSource | null = null
let noticeTimer: number | undefined
const seenEvents = new Set<string>()

const wideQuery = window.matchMedia('(min-width: 1281px)')
const traceOpen = ref(wideQuery.matches)

const currentRunId = computed(() => {
  const value = route.params.runId
  return Array.isArray(value) ? value[0] : value
})

const hasRun = computed(() => !!currentRunId.value)
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

async function loadRun(runId: string) {
  closeStream()
  loadingRun.value = true
  error.value = ''
  events.value = []
  runInfo.value = null
  finalOutput.value = null
  finalError.value = null
  runStatus.value = null
  seenEvents.clear()

  try {
    const [run, steps] = await Promise.all([
      api.get<RunRead>(`/api/runs/${runId}`),
      api.get<Page<StepRead>>(`/api/runs/${runId}/steps?page_size=500`),
    ])
    runInfo.value = run
    userText.value = run.input
    input.value = ''
    agentId.value = run.agent_id
    events.value = steps.items.map(stepToEvent)
    for (const event of events.value) {
      seenEvents.add(`${event.event_type}|${event.step_no}|${event.timestamp}`)
    }
    applyRunStatus(run)
    finalOutput.value = run.output ?? null
    finalError.value = run.error_message ?? null

    if (run.status === 'PENDING' || run.status === 'RUNNING') {
      openStream(runId)
    }

    if (!agents.value.some((agent) => agent.id === run.agent_id)) {
      try {
        const agent = await api.get<Agent>(`/api/agents/${run.agent_id}`)
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
  try {
    const run = await api.get<RunRead>(`/api/runs/${runId}`)
    runInfo.value = run
    applyRunStatus(run)
    if (run.output) finalOutput.value = run.output
    if (run.error_message) finalError.value = run.error_message
    updateConversation(runId, { status: run.status })
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
  userText.value = ''
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
    closeStream()
    if (currentRunId.value) void refreshRun(currentRunId.value)
  } else if (parsed.event_type === 'RUN_FAILED') {
    const stopReason = (parsed.data?.stop_reason as string) ?? ''
    finalOutput.value = (parsed.data?.partial_output as string) ?? null
    finalError.value =
      (parsed.data?.error_message as string) ?? stopReason ?? '执行失败'
    runStatus.value = stopReason === 'CANCELLED' ? 'cancelled' : 'failed'
    closeStream()
    if (currentRunId.value) void refreshRun(currentRunId.value)
  }
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

function onAgentChange(id: number) {
  agentId.value = id
  localStorage.setItem('agenthub.lastAgent', String(id))
  if (hasRun.value) {
    router.push('/chat')
    resetSession()
  }
}

async function onModelChange(model: string) {
  const agent = selectedAgent.value
  if (!agent || model === agent.model) return
  try {
    const updated = await api.put<Agent>(`/api/agents/${agent.id}`, { model })
    const index = agents.value.findIndex((item) => item.id === updated.id)
    if (index >= 0) agents.value[index] = updated
    showNotice(`已更新「${updated.name}」的模型：${updated.model}`)
  } catch (e) {
    error.value = errorMessage(e, '模型切换失败')
  }
}

async function send() {
  if (agentId.value == null) {
    error.value = '请先选择 Agent'
    return
  }
  const text = input.value.trim()
  if (!text || isRunning.value) return

  error.value = ''
  finalOutput.value = null
  finalError.value = null
  events.value = []
  seenEvents.clear()
  userText.value = text
  runStatus.value = 'running'
  running.value = true
  const sent = text
  input.value = ''

  try {
    const run = await api.post<RunRead>(`/api/agents/${agentId.value}/runs`, {
      input: sent,
      max_steps: maxSteps.value ?? undefined,
    })
    runInfo.value = run
    upsertConversation({
      runId: run.id,
      agentId: run.agent_id,
      agentName: selectedAgent.value?.name ?? `Agent ${run.agent_id}`,
      model: selectedAgent.value?.model ?? '',
      title: sent.slice(0, 48),
      createdAt: new Date().toISOString(),
      status: run.status,
    })
    if (currentRunId.value !== run.id) {
      await router.push(`/chat/${run.id}`)
    }
    openStream(run.id)
  } catch (e) {
    running.value = false
    runStatus.value = null
    error.value = errorMessage(e, '创建任务失败')
    input.value = sent
  }
}

function onWideChange(event: MediaQueryListEvent) {
  if (!event.matches) traceOpen.value = false
}

watch(currentRunId, (runId) => {
  if (!runId) {
    resetSession()
    return
  }
  if (runId === runInfo.value?.id) return
  void loadRun(runId)
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
  if (currentRunId.value) {
    await loadRun(currentRunId.value)
  } else {
    const queryAgent = Number(route.query.agent)
    if (queryAgent && agents.value.some((agent) => agent.id === queryAgent)) {
      agentId.value = queryAgent
    }
    void nextTick(() => composerRef.value?.focus())
  }
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
          <span v-if="selectedAgent" class="head-model">{{ selectedAgent.model }}</span>
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
          :model="selectedAgent?.model ?? ''"
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
            <div class="msg user">
              <div class="bubble">{{ userText || runInfo?.input || '' }}</div>
            </div>

            <div class="msg assistant">
              <div class="assistant-line">
                <span class="assistant-avatar">A</span>
                <span class="assistant-name">{{ selectedAgent?.name ?? 'Agent' }}</span>
                <span v-if="runInfo" class="assistant-run">{{ runInfo.id }}</span>
              </div>

              <div v-if="loadingRun" class="thinking">
                <span class="pulse"></span>加载会话…
              </div>

              <template v-else>
                <div v-if="isRunning && !events.length" class="thinking">
                  <span class="pulse"></span>Agent 正在思考…
                </div>

                <ProcessList :events="events" />

                <div v-if="finalOutput" class="answer">{{ finalOutput }}</div>

                <div v-if="finalError" class="error-box answer-error">
                  <span>{{ finalError }}</span>
                  <router-link v-if="showModelFix" to="/settings/models">去配置模型</router-link>
                </div>

                <div v-if="error" class="error-box answer-error">{{ error }}</div>

                <div v-if="runInfo && !isRunning" class="run-meta">
                  <span class="badge" :class="runStatus ?? ''">
                    {{
                      runStatus === 'success'
                        ? '成功'
                        : runStatus === 'partial'
                          ? '部分完成'
                          : runStatus === 'failed'
                            ? '失败'
                            : runStatus === 'cancelled'
                              ? '已取消'
                              : runInfo.status
                    }}
                  </span>
                  <span>{{ runInfo.llm_calls }} 次 LLM</span>
                  <span>{{ runInfo.tool_calls }} 次工具</span>
                  <span>{{ runInfo.step_count }} 步</span>
                </div>
              </template>
            </div>
          </div>
        </div>

        <div class="composer-wrap">
          <ChatComposer
            ref="composerRef"
            :agents="agents"
            :agent-id="agentId"
            :model="selectedAgent?.model ?? ''"
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

<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { api, errorMessage, formatDuration } from '../api/http'
import TraceTimeline from './TraceTimeline.vue'
import type { RunRead, TraceEvent } from '../types/api'

const props = defineProps<{
  agentId: number
  agentName?: string
  defaultSteps?: number | null
}>()

const input = ref('')
const maxSteps = ref<number | null>(null)
// 留空不是“无限制”，而是使用该 Agent 配置的 max_steps
const stepsPlaceholder = computed(() =>
  props.defaultSteps ? `默认 ${props.defaultSteps}` : '跟随 Agent',
)
const running = ref(false)
const runInfo = ref<RunRead | null>(null)
const events = ref<TraceEvent[]>([])
const finalOutput = ref<string | null>(null)
const finalError = ref<string | null>(null)
const runStatus = ref<'running' | 'success' | 'partial' | 'failed' | 'cancelled' | null>(null)
const error = ref('')

let es: EventSource | null = null

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

function handleEvent(raw: MessageEvent) {
  let parsed: TraceEvent
  try {
    parsed = JSON.parse(raw.data)
  } catch {
    return
  }
  events.value.push(parsed)

  if (parsed.event_type === 'RUN_FINISHED') {
    const stopReason = (parsed.data?.stop_reason as string) ?? ''
    finalOutput.value = (parsed.data?.output as string) ?? null
    runStatus.value = stopReason === 'MAX_STEPS' ? 'partial' : 'success'
    closeStream()
  } else if (parsed.event_type === 'RUN_FAILED') {
    const stopReason = (parsed.data?.stop_reason as string) ?? ''
    finalOutput.value = (parsed.data?.partial_output as string) ?? null
    finalError.value = (parsed.data?.error_message as string) ?? stopReason ?? '执行失败'
    runStatus.value = stopReason === 'CANCELLED' ? 'cancelled' : 'failed'
    closeStream()
  }
}

function openStream(runId: string) {
  es = new EventSource(`/api/runs/${runId}/events`)
  for (const name of SSE_EVENT_NAMES) {
    es.addEventListener(name, handleEvent as EventListener)
  }
  es.onerror = () => closeStream()
}

function closeStream() {
  if (es) {
    es.close()
    es = null
  }
  running.value = false
}

async function startRun() {
  error.value = ''
  finalOutput.value = null
  finalError.value = null
  runStatus.value = null
  runInfo.value = null
  events.value = []

  if (!input.value.trim()) {
    error.value = '请输入任务描述'
    return
  }

  running.value = true
  runStatus.value = 'running'
  try {
    const run = await api.post<RunRead>(`/api/agents/${props.agentId}/runs`, {
      input: input.value,
      max_steps: maxSteps.value ?? undefined,
    })
    runInfo.value = run
    openStream(run.id)
  } catch (e) {
    running.value = false
    runStatus.value = null
    error.value = errorMessage(e, '创建任务失败')
  }
}

function statusText(): string {
  const map: Record<string, string> = {
    running: '运行中…',
    success: '成功',
    partial: '部分完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return runStatus.value ? map[runStatus.value] : ''
}

onUnmounted(closeStream)
</script>

<template>
  <div class="run-panel">
    <div class="run-form">
      <label class="field">
        <span>任务描述</span>
        <textarea
          v-model="input"
          rows="4"
          maxlength="8000"
          placeholder="描述任务，例如：查一下仓库最近 3 个 issue，并按优先级总结"
        ></textarea>
      </label>

      <div class="run-row">
        <label class="steps">
          最大执行步数
          <input v-model.number="maxSteps" type="number" min="1" max="20" :placeholder="stepsPlaceholder" />
        </label>
        <button class="btn-primary" type="button" :disabled="running" @click="startRun">
          {{ running ? '运行中…' : '运行' }}
        </button>
      </div>

      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="runInfo" class="muted run-id">
        任务 <code>{{ runInfo.id }}</code> · {{ agentName ?? `Agent #${agentId}` }}
      </p>
    </div>

    <div v-if="runStatus" class="run-result" :class="runStatus">
      <div class="result-head">
        <span class="badge" :class="runStatus">{{ statusText() }}</span>
        <span v-if="runInfo" class="muted">
          {{ runInfo.llm_calls }} 次模型调用 · {{ runInfo.tool_calls }} 次工具 ·
          {{ formatDuration(runInfo.duration_ms) }}
        </span>
      </div>
      <pre v-if="finalOutput" class="output">{{ finalOutput }}</pre>
      <p v-if="finalError" class="error">{{ finalError }}</p>
    </div>

    <div class="trace-block">
      <h3>执行过程</h3>
      <TraceTimeline :events="events" />
    </div>
  </div>
</template>

<style scoped>
.run-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.run-form {
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}

.field span {
  font-size: 12.5px;
  color: var(--text-secondary);
}

.field textarea {
  resize: vertical;
}

.run-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.steps {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-muted);
}

.steps input {
  width: 120px;
}

.run-id {
  margin: 10px 0 0;
  font-size: 11.5px;
}

.run-result {
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 14px;
}

.result-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 11.5px;
}

.output {
  margin: 10px 0 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.7;
}

.trace-block h3 {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
}
</style>

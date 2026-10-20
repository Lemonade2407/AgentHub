<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import TraceTimeline, { type TraceEvent } from '../components/TraceTimeline.vue'

// DTO 与 AgentHub_接口契约文档.md §3.4 / §5 一致
interface Agent {
  id: number
  name: string
  model: string
  enabled: boolean
}

interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

interface RunRead {
  id: string
  agent_id: number
  thread_id: string
  status: string
  stop_reason: string | null
  input: string
  output: string | null
  max_steps: number
  llm_calls: number
  tool_calls: number
  step_count: number
}

const agents = ref<Agent[]>([])
const agentId = ref<number | null>(null)
const input = ref('')
const maxSteps = ref<number | null>(null)

const running = ref(false)
const runInfo = ref<RunRead | null>(null)
const events = ref<TraceEvent[]>([])
const finalOutput = ref<string | null>(null)
const finalError = ref<string | null>(null)
const runStatus = ref<'running' | 'success' | 'partial' | 'failed' | 'cancelled' | null>(null)
const error = ref('')

let es: EventSource | null = null

function failMessage(resp: Response): Promise<string> {
  return resp
    .json()
    .catch(() => null)
    .then((b) => b?.message ?? `HTTP ${resp.status}`)
}

function openStream(runId: string) {
  es = new EventSource(`/api/runs/${runId}/events`)
  es.onmessage = (ev) => {
    let parsed: TraceEvent
    try {
      parsed = JSON.parse(ev.data)
    } catch {
      return // 心跳等无法解析的帧直接忽略
    }
    events.value.push(parsed)
    // §5.4：以 event_type + stop_reason 判断最终状态，不能只看事件名
    if (parsed.event_type === 'RUN_FINISHED') {
      const stopReason = (parsed.data?.stop_reason as string) ?? ''
      finalOutput.value = (parsed.data?.output as string) ?? null
      runStatus.value = stopReason === 'MAX_STEPS' ? 'partial' : 'success'
      closeStream()
    } else if (parsed.event_type === 'RUN_FAILED') {
      const stopReason = (parsed.data?.stop_reason as string) ?? ''
      finalOutput.value = (parsed.data?.partial_output as string) ?? null
      finalError.value = (parsed.data?.error_message as string) ?? stopReason ?? 'Run 失败'
      runStatus.value = stopReason === 'CANCELLED' ? 'cancelled' : 'failed'
      closeStream()
    }
  }
  es.onerror = () => {
    // 连接异常或服务端关闭。run 结束后事件已处理并关闭；此处兜底清理
    closeStream()
  }
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

  if (agentId.value == null) {
    error.value = '请先选择 Agent'
    return
  }
  if (!input.value.trim()) {
    error.value = '请输入任务描述'
    return
  }

  running.value = true
  try {
    const resp = await fetch(`/api/agents/${agentId.value}/runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        input: input.value,
        max_steps: maxSteps.value ?? undefined, // Run 级唯一可覆盖项，契约 §3.4
      }),
    })
    if (!resp.ok) {
      running.value = false
      throw new Error(await failMessage(resp))
    }
    const run: RunRead = await resp.json()
    runInfo.value = run
    openStream(run.id)
  } catch (e) {
    running.value = false
    error.value = e instanceof Error ? e.message : String(e)
  }
}

function statusText(): string {
  const map = {
    running: '运行中…',
    success: '成功',
    partial: '部分完成',
    failed: '失败',
    cancelled: '已取消',
  } as const
  return runStatus.value ? map[runStatus.value] : ''
}

onMounted(async () => {
  try {
    const resp = await fetch('/api/agents?page_size=100')
    if (!resp.ok) return
    const data: Page<Agent> = await resp.json()
    agents.value = data.items.filter((a) => a.enabled)
    if (agents.value.length) agentId.value = agents.value[0].id
  } catch {
    // 列表加载失败不阻断页面
  }
})

onUnmounted(closeStream)
</script>

<template>
  <section class="page">
    <h1>Playground</h1>

    <div class="run-panel">
      <div class="row">
        <label>Agent</label>
        <select v-model.number="agentId">
          <option v-for="a in agents" :key="a.id" :value="a.id">
            #{{ a.id }} · {{ a.name }}（{{ a.model }}）
          </option>
        </select>
      </div>

      <div class="row">
        <label>任务描述 *</label>
        <textarea v-model="input" rows="4" maxlength="8000" placeholder="例如：查一下 AgentHub 仓库最近 3 个 issue，并总结"></textarea>
      </div>

      <div class="row inline">
        <label>最大执行步数</label>
        <input v-model.number="maxSteps" type="number" min="1" max="20" placeholder="不填则用 Agent 配置" />
      </div>

      <button class="btn-primary" :disabled="running" @click="startRun">
        {{ running ? '运行中…' : '运行' }}
      </button>

      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="runInfo" class="muted">
        run_id：<code>{{ runInfo.id }}</code>
        &middot; 已用 LLM {{ runInfo.llm_calls }} 次 / 工具 {{ runInfo.tool_calls }} 次
      </p>
    </div>

    <div v-if="runStatus" class="result" :class="runStatus">
      <span class="badge">{{ statusText() }}</span>
      <pre v-if="finalOutput" class="output">{{ finalOutput }}</pre>
      <p v-if="finalError" class="error">{{ finalError }}</p>
    </div>

    <h2 class="sub-title">执行过程</h2>
    <TraceTimeline :events="events" />
  </section>
</template>

<style scoped>
.run-panel {
  max-width: 640px;
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 16px;
}

.row {
  margin-bottom: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.row.inline {
  flex-direction: row;
  align-items: center;
  gap: 12px;
}

.row label {
  font-weight: 600;
  font-size: 14px;
}

.row select {
  padding: 8px 10px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
}

.row textarea {
  padding: 8px 10px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-family: inherit;
}

.row input[type='number'] {
  width: 120px;
  padding: 8px 10px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
}

.btn-primary {
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  background: #1a7f37;
  color: #fff;
  cursor: pointer;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.result {
  max-width: 640px;
  margin-top: 16px;
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 14px;
}

.badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
}

.result.success .badge {
  background: #e6f4ea;
  color: #1a7f37;
}

.result.partial .badge {
  background: #fff8c5;
  color: #7d4e00;
}

.result.failed .badge,
.result.cancelled .badge {
  background: #ffebe9;
  color: #cf222e;
}

.result.running .badge {
  background: #ddf4ff;
  color: #0969da;
}

.output {
  margin: 12px 0 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 14px;
}

.sub-title {
  font-size: 16px;
  margin: 24px 0 8px;
}

.error {
  color: #d1242f;
}
</style>

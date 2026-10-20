<script setup lang="ts">
// TraceEvent 公共外层字段契约见 AgentHub_接口契约文档.md §5.3
export interface TraceEvent {
  run_id: string
  step_no: number
  event_type: string
  status: string
  node: string | null
  tool: string | null
  duration_ms: number | null
  data: Record<string, unknown> | null
  timestamp: string
}

defineProps<{
  events: TraceEvent[]
}>()

function eventLabel(eventType: string): string {
  const map: Record<string, string> = {
    RUN_STARTED: 'Run 开始',
    TOOL_CANDIDATES: '工具筛选',
    LLM_STARTED: 'LLM 调用',
    LLM_FINISHED: 'LLM 完成',
    TOOL_CALL_STARTED: '工具调用',
    TOOL_CALL_FINISHED: '工具完成',
    STATE_UPDATED: '状态更新',
    RUN_FINISHED: 'Run 完成',
    RUN_FAILED: 'Run 失败',
  }
  return map[eventType] ?? eventType
}

function statusClass(status: string): string {
  if (status === 'SUCCESS') return 'on'
  if (status === 'RUNNING') return 'running'
  return 'error'
}

function fmtTs(ts: string): string {
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  return d.toTimeString().slice(0, 8)
}

function fmtDuration(ms: number | null): string {
  if (ms == null) return ''
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(2)}s`
}

function jsonText(data: Record<string, unknown> | null): string {
  if (data == null) return ''
  try {
    return JSON.stringify(data, null, 2)
  } catch {
    return String(data)
  }
}
</script>

<template>
  <div class="timeline">
    <div v-for="(e, i) in events" :key="i" class="event">
      <div class="rail">
        <span class="dot" :class="statusClass(e.status)"></span>
        <span v-if="i < events.length - 1" class="line"></span>
      </div>

      <div class="card">
        <div class="head">
          <span class="label">{{ eventLabel(e.event_type) }}</span>
          <span class="meta">
            step {{ e.step_no }}
            <template v-if="e.node">&middot; {{ e.node }}</template>
            <template v-if="e.tool">&middot; <code>{{ e.tool }}</code></template>
            <template v-if="fmtDuration(e.duration_ms)">&middot; {{ fmtDuration(e.duration_ms) }}</template>
          </span>
          <span class="time">{{ fmtTs(e.timestamp) }}</span>
        </div>

        <details v-if="e.data" class="detail">
          <summary>查看数据</summary>
          <pre>{{ jsonText(e.data) }}</pre>
        </details>
      </div>
    </div>

    <p v-if="!events.length" class="muted empty">尚无事件。提交任务后，Agent 的每一步执行过程会实时显示在这里。</p>
  </div>
</template>

<style scoped>
.timeline {
  padding-top: 4px;
}

.event {
  display: flex;
  gap: 12px;
}

.rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 12px;
  flex-shrink: 0;
}

.dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  margin-top: 6px;
}

.dot.on {
  background: #1a7f37;
}

.dot.running {
  background: #1f6feb;
}

.dot.error {
  background: #cf222e;
}

.line {
  flex: 1;
  width: 2px;
  background: var(--border-color);
  margin: 4px 0;
}

.card {
  flex: 1;
  margin-bottom: 10px;
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px 12px;
}

.head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.label {
  font-weight: 600;
  font-size: 14px;
}

.meta {
  font-size: 12px;
  color: var(--text-muted);
}

.time {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-muted);
}

.detail {
  margin-top: 8px;
  font-size: 13px;
}

.detail summary {
  cursor: pointer;
  color: var(--text-muted);
}

.detail pre {
  background: var(--surface-muted);
  border-radius: 6px;
  padding: 10px;
  font-size: 12px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.empty {
  text-align: center;
}
</style>

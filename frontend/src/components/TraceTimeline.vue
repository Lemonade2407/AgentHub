<script setup lang="ts">
import type { TraceEvent } from '../types/api'

defineProps<{
  events: TraceEvent[]
}>()

const LABELS: Record<string, string> = {
  RUN_STARTED: '任务开始',
  TOOL_CANDIDATES: '工具筛选',
  SKILL_INJECTED: 'Skill 注入',
  SKILL_TOOL_MISSING: 'Skill 工具缺失',
  LLM_STARTED: '模型调用',
  LLM_FINISHED: '模型完成',
  TOOL_CALL_STARTED: '工具调用',
  TOOL_CALL_FINISHED: '工具完成',
  STATE_UPDATED: '状态更新',
  RUN_FINISHED: '任务完成',
  RUN_FAILED: '任务失败',
}

function eventLabel(eventType: string): string {
  return LABELS[eventType] ?? eventType
}

interface CandidateView {
  name: string
  score: number | null
}

/** FR-SEL-05：把 TOOL_CANDIDATES 的 names / scores 一一对应展示。 */
function candidateRows(data: Record<string, unknown> | null): CandidateView[] {
  if (!data) return []
  const names = Array.isArray(data.names) ? data.names : []
  const scores = Array.isArray(data.scores) ? data.scores : []
  return names.map((name, index) => {
    const score = scores[index]
    return {
      name: String(name),
      score: typeof score === 'number' ? score : null,
    }
  })
}

function text(value: unknown, fallback = ''): string {
  return value == null ? fallback : String(value)
}

function names(value: unknown): string {
  return Array.isArray(value) ? value.map((item) => String(item)).join(', ') : ''
}

function statusClass(status: string): string {
  if (status === 'SUCCESS') return 'on'
  if (status === 'RUNNING') return 'running'
  if (status === 'SKIPPED') return 'skipped'
  return 'error'
}

function fmtTs(ts: string): string {
  const date = new Date(ts)
  if (Number.isNaN(date.getTime())) return ts
  return date.toTimeString().slice(0, 8)
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
    <div v-for="(event, index) in events" :key="index" class="event">
      <div class="rail">
        <span class="dot" :class="statusClass(event.status)"></span>
        <span v-if="index < events.length - 1" class="line"></span>
      </div>

      <div class="card">
        <div class="head">
          <span class="label">{{ eventLabel(event.event_type) }}</span>
          <span class="meta">
            步骤 {{ event.step_no }}
            <template v-if="event.node">· {{ event.node }}</template>
            <template v-if="event.tool">· <code>{{ event.tool }}</code></template>
            <template v-if="fmtDuration(event.duration_ms)">· {{ fmtDuration(event.duration_ms) }}</template>
          </span>
          <span class="time">{{ fmtTs(event.timestamp) }}</span>
        </div>

        <div v-if="event.event_type === 'TOOL_CANDIDATES' && event.data" class="summary-line">
          <span class="muted">候选工具</span>
          <span v-for="candidate in candidateRows(event.data)" :key="candidate.name" class="chip">
            <code>{{ candidate.name }}</code>
            <em v-if="candidate.score != null">{{ candidate.score.toFixed(2) }}</em>
          </span>
        </div>

        <div v-else-if="event.event_type === 'SKILL_INJECTED' && event.data" class="summary-line">
          <span class="chip on">
            Skill <code>{{ text(event.data.slug) }}</code> v{{ text(event.data.version) }}
          </span>
          <span v-if="names(event.data.tools)" class="muted">贡献工具：{{ names(event.data.tools) }}</span>
        </div>

        <div v-else-if="event.event_type === 'SKILL_TOOL_MISSING' && event.data" class="summary-line">
          <span class="chip bad">缺失 <code>{{ text(event.data.tool) }}</code></span>
          <span class="muted">
            来自 {{ text(event.data.skill_slug) }} ·
            {{ event.data.required ? '必填，已拒绝运行' : '可选，已跳过' }}
          </span>
        </div>

        <div
          v-else-if="event.event_type === 'RUN_STARTED' && event.data && (event.data.model_api_name || event.data.model_key)"
          class="summary-line"
        >
          <span v-if="event.data.model_api_name" class="chip">
            模型 API <code>{{ text(event.data.model_api_name) }}</code>
          </span>
          <span v-if="event.data.model_key" class="chip">
            <code>{{ text(event.data.model_key) }}</code>
          </span>
        </div>

        <details v-if="event.data" class="detail">
          <summary>查看明细</summary>
          <pre>{{ jsonText(event.data) }}</pre>
        </details>
      </div>
    </div>

    <p v-if="!events.length" class="muted empty">
      尚无事件。提交任务后，Agent 的每一步执行过程会实时显示在这里。
    </p>
  </div>
</template>

<style scoped>
.timeline {
  padding-top: 2px;
}

.event {
  display: flex;
  gap: 10px;
}

.rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 10px;
  flex-shrink: 0;
}

.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  margin-top: 8px;
  background: var(--text-muted);
}

.dot.on {
  background: var(--success);
}

.dot.running {
  background: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.dot.skipped {
  background: var(--warn);
}

.dot.error {
  background: var(--danger);
}

.line {
  flex: 1;
  width: 1px;
  background: var(--border-color);
  margin: 4px 0;
}

.card {
  flex: 1;
  min-width: 0;
  margin-bottom: 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
}

.head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.label {
  font-weight: 600;
  font-size: 12.5px;
  color: var(--text-main);
}

.meta {
  font-size: 11px;
  color: var(--text-muted);
}

.time {
  margin-left: auto;
  font-size: 10.5px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.detail {
  margin-top: 6px;
  font-size: 12px;
}

.summary-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  font-size: 11.5px;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
}

.chip em {
  font-style: normal;
  color: var(--text-muted);
}

.chip.on {
  background: var(--success-soft);
  border-color: rgba(63, 185, 80, 0.35);
  color: var(--success);
}

.chip.bad {
  background: var(--danger-soft);
  border-color: rgba(240, 93, 93, 0.35);
  color: var(--danger);
}

.detail summary {
  cursor: pointer;
  color: var(--text-muted);
  font-size: 11.5px;
}

.detail pre {
  margin: 6px 0 0;
  background: var(--bg-base);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 8px;
  font-size: 11px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 240px;
}

.empty {
  text-align: center;
  font-size: 12px;
  line-height: 1.6;
}
</style>

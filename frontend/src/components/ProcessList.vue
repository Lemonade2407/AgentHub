<script setup lang="ts">
import { computed } from 'vue'
import { formatDuration } from '../api/http'
import type { TraceEvent } from '../types/api'

interface ProcessItem {
  key: string
  title: string
  status: string
  duration: number | null
  chips?: string[]
  body?: string
}

const props = defineProps<{
  events: TraceEvent[]
}>()

function text(value: unknown, fallback = ''): string {
  return value == null ? fallback : String(value)
}

function namesOf(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)) : []
}

function pretty(data: unknown): string {
  try {
    return JSON.stringify(data, null, 2)
  } catch {
    return String(data)
  }
}

/** 把 Trace 事件压缩成对话流里的可折叠过程块（§6.3）。 */
const items = computed<ProcessItem[]>(() => {
  const result: ProcessItem[] = []
  const pendingTools = new Map<string, ProcessItem>()

  for (const event of props.events) {
    const data = event.data ?? {}
    switch (event.event_type) {
      case 'SKILL_INJECTED':
        result.push({
          key: `skill-${event.step_no}-${text(data.slug)}`,
          title: `注入 Skill · ${text(data.slug)} v${text(data.version)}`,
          status: 'SUCCESS',
          duration: null,
          chips: namesOf(data.tools),
          body: Object.keys(data).length ? pretty(data) : undefined,
        })
        break
      case 'SKILL_TOOL_MISSING':
        result.push({
          key: `missing-${event.step_no}-${text(data.tool)}`,
          title: `Skill 工具缺失 · ${text(data.tool)}`,
          status: 'FAILED',
          duration: null,
          chips: [text(data.skill_slug), data.required ? 'required' : 'optional'],
          body: pretty(data),
        })
        break
      case 'TOOL_CANDIDATES': {
        const candidates = namesOf(data.names)
        const scores = Array.isArray(data.scores) ? data.scores : []
        result.push({
          key: `candidates-${event.step_no}`,
          title: `候选工具 ${candidates.length} 个（K=${text(data.top_k, '-')}）`,
          status: 'SUCCESS',
          duration: event.duration_ms,
          chips: candidates.map((name, index) => {
            const score = scores[index]
            return typeof score === 'number' ? `${name} · ${score.toFixed(2)}` : name
          }),
        })
        break
      }
      case 'TOOL_CALL_STARTED': {
        const item: ProcessItem = {
          key: `tool-${event.step_no}-${text(event.tool)}`,
          title: `调用工具 · ${text(event.tool, 'unknown')}`,
          status: 'RUNNING',
          duration: null,
          body: Object.keys(data).length ? pretty(data) : undefined,
        }
        pendingTools.set(item.key, item)
        result.push(item)
        break
      }
      case 'TOOL_CALL_FINISHED': {
        const key = `tool-${event.step_no}-${text(event.tool)}`
        const target = pendingTools.get(key)
        if (target) {
          target.status = event.status
          target.duration = event.duration_ms ?? target.duration
          if (Object.keys(data).length) target.body = pretty(data)
        } else {
          result.push({
            key,
            title: `工具完成 · ${text(event.tool, 'unknown')}`,
            status: event.status,
            duration: event.duration_ms,
            body: Object.keys(data).length ? pretty(data) : undefined,
          })
        }
        break
      }
      case 'LLM_FINISHED':
        result.push({
          key: `llm-${event.step_no}-${event.timestamp}`,
          title: `模型响应 · step ${event.step_no}`,
          status: event.status,
          duration: event.duration_ms,
        })
        break
      default:
        break
    }
  }

  return result
})
</script>

<template>
  <div v-if="items.length" class="process">
    <details class="process-wrap">
      <summary class="process-summary">
        <span class="spark"></span>
        执行过程
        <span class="count">{{ items.length }}</span>
      </summary>
      <div class="process-body">
        <template v-for="item in items" :key="item.key">
          <details v-if="item.chips?.length || item.body" class="proc">
            <summary class="proc-head">
              <span class="dot" :class="item.status.toLowerCase()"></span>
              <span class="proc-title">{{ item.title }}</span>
              <span v-if="item.duration != null" class="proc-dur">{{ formatDuration(item.duration) }}</span>
            </summary>
            <div class="proc-detail">
              <div v-if="item.chips?.length" class="chips">
                <span v-for="chip in item.chips" :key="chip" class="tag">{{ chip }}</span>
              </div>
              <pre v-if="item.body">{{ item.body }}</pre>
            </div>
          </details>
          <div v-else class="proc">
            <div class="proc-head">
              <span class="dot" :class="item.status.toLowerCase()"></span>
              <span class="proc-title">{{ item.title }}</span>
              <span v-if="item.duration != null" class="proc-dur">{{ formatDuration(item.duration) }}</span>
            </div>
          </div>
        </template>
      </div>
    </details>
  </div>
</template>

<style scoped>
.process {
  margin-top: 10px;
}

.process-wrap {
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-panel);
  overflow: hidden;
}

.process-summary {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 10px;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  list-style: none;
}

.process-summary::-webkit-details-marker {
  display: none;
}

.spark {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.count {
  margin-left: auto;
  font-size: 10.5px;
  color: var(--text-muted);
}

.process-body {
  padding: 2px 8px 8px;
  border-top: 1px solid var(--border-color);
}

.proc {
  margin-top: 4px;
  border-radius: 6px;
}

.proc-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 6px;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  list-style: none;
}

.proc-head::-webkit-details-marker {
  display: none;
}

.proc-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.proc-dur {
  font-size: 10.5px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--text-muted);
}

.dot.success {
  background: var(--success);
}

.dot.running {
  background: var(--accent);
}

.dot.failed {
  background: var(--danger);
}

.dot.skipped {
  background: var(--warn);
}

.proc-detail {
  padding: 2px 6px 8px 20px;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-bottom: 4px;
}

.proc-detail pre {
  margin: 0;
  padding: 8px;
  max-height: 220px;
  overflow: auto;
  background: var(--bg-base);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-size: 11px;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-all;
}
</style>

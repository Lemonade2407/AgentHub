<script setup lang="ts">
import { computed } from 'vue'
import { formatDuration } from '../api/http'
import type { RunRead, TraceEvent } from '../types/api'
import TraceTimeline from './TraceTimeline.vue'

const props = defineProps<{
  run: RunRead | null
  events: TraceEvent[]
  running?: boolean
}>()

defineEmits<{
  (e: 'close'): void
}>()

const STATUS_TEXT: Record<string, string> = {
  PENDING: '等待执行',
  RUNNING: '运行中',
  SUCCESS: '成功',
  PARTIAL: '部分完成',
  FAILED: '失败',
  CANCELLED: '已取消',
}

const status = computed(() => props.run?.status ?? (props.running ? 'RUNNING' : null))
const statusText = computed(() => (status.value ? (STATUS_TEXT[status.value] ?? status.value) : '未开始'))
</script>

<template>
  <aside class="trace-panel">
    <header class="trace-head">
      <div>
        <h3>执行过程</h3>
        <p>实时事件 · 可展开查看原始数据</p>
      </div>
      <button class="trace-close" type="button" aria-label="收起执行过程" @click="$emit('close')">
        <svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18" /></svg>
      </button>
    </header>

    <div v-if="status" class="trace-status">
      <span class="badge" :class="status.toLowerCase()">{{ statusText }}</span>
      <span v-if="run" class="trace-hint">run {{ run.id.slice(0, 10) }}…</span>
    </div>

    <div v-if="run" class="trace-stats">
      <div class="stat">
        <span class="stat-value">{{ run.step_count }}</span>
        <span class="stat-label">步骤</span>
      </div>
      <div class="stat">
        <span class="stat-value">{{ run.llm_calls }}</span>
        <span class="stat-label">LLM</span>
      </div>
      <div class="stat">
        <span class="stat-value">{{ run.tool_calls }}</span>
        <span class="stat-label">工具</span>
      </div>
      <div class="stat">
        <span class="stat-value">{{ formatDuration(run.duration_ms) }}</span>
        <span class="stat-label">耗时</span>
      </div>
    </div>

    <div class="trace-scroll">
      <TraceTimeline :events="events" />
    </div>
  </aside>
</template>

<style scoped>
.trace-panel {
  width: 380px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-left: 1px solid var(--border-color);
  background: var(--bg-panel);
}

.trace-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px 10px;
  border-bottom: 1px solid var(--border-color);
}

.trace-head h3 {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
}

.trace-head p {
  margin: 2px 0 0;
  font-size: 11px;
  color: var(--text-muted);
}

.trace-close {
  width: 26px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-color);
  border-radius: 7px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.trace-close:hover {
  background: var(--bg-hover);
  color: var(--text-main);
}

.trace-close svg {
  width: 13px;
  height: 13px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
}

.trace-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px 0;
}

.trace-hint {
  font-size: 11px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.trace-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
  padding: 10px 16px 12px;
  border-bottom: 1px solid var(--border-color);
}

.stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  padding: 6px 4px;
  border-radius: 8px;
  background: var(--bg-elevated);
}

.stat-value {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-main);
  font-family: var(--font-mono);
}

.stat-label {
  font-size: 10px;
  color: var(--text-muted);
}

.trace-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 14px 24px;
}

@media (max-width: 1280px) {
  .trace-panel {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    z-index: 55;
    width: min(92vw, 400px);
    box-shadow: var(--shadow-pop);
  }
}
</style>

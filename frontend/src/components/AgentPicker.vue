<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import type { Agent } from '../types/api'

const props = defineProps<{
  agents: Agent[]
  modelValue: number | null
  disabled?: boolean
  label?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: number): void
}>()

const root = ref<HTMLElement | null>(null)
const open = ref(false)
const keyword = ref('')

const selected = computed(() => props.agents.find((agent) => agent.id === props.modelValue) ?? null)

const filtered = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  if (!query) return props.agents
  return props.agents.filter((agent) =>
    `${agent.name} ${agent.description ?? ''} ${agent.model}`.toLowerCase().includes(query),
  )
})

function onDocumentClick(event: MouseEvent) {
  if (root.value && !root.value.contains(event.target as Node)) close()
}

function close() {
  open.value = false
  document.removeEventListener('click', onDocumentClick)
}

function toggle() {
  if (props.disabled) return
  if (open.value) {
    close()
    return
  }
  open.value = true
  keyword.value = ''
  document.addEventListener('click', onDocumentClick)
}

function choose(agent: Agent) {
  emit('update:modelValue', agent.id)
  close()
}

onBeforeUnmount(() => document.removeEventListener('click', onDocumentClick))
</script>

<template>
  <div ref="root" class="picker" :class="{ disabled }">
    <button class="picker-trigger" type="button" :disabled="disabled" @click.stop="toggle">
      <span class="picker-label">{{ label ?? 'Agent' }}</span>
      <span class="picker-value">{{ selected?.name ?? '默认' }}</span>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
    </button>

    <div v-if="open" class="picker-menu">
      <input
        v-if="agents.length > 5"
        v-model="keyword"
        type="search"
        class="picker-search"
        placeholder="搜索 Agent"
      />
      <div class="picker-list">
        <button
          v-for="agent in filtered"
          :key="agent.id"
          class="picker-option"
          :class="{ active: agent.id === modelValue }"
          type="button"
          @click="choose(agent)"
        >
          <span class="option-name">{{ agent.name }}</span>
          <span class="option-hint">{{ agent.model }}</span>
        </button>
        <p v-if="!filtered.length" class="picker-empty">还没有 Agent</p>
      </div>
      <router-link to="/agents/new" class="picker-foot" @click="close">+ 新建 Agent</router-link>
    </div>
  </div>
</template>

<style scoped>
.picker {
  position: relative;
}

.picker.disabled {
  opacity: 0.6;
}

.picker-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 9px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-elevated);
  color: var(--text-main);
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
  max-width: 240px;
}

.picker-trigger:hover {
  border-color: var(--border-strong);
}

.picker-label {
  color: var(--text-muted);
}

.picker-value {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.picker-trigger svg {
  width: 12px;
  height: 12px;
  fill: none;
  stroke: var(--text-muted);
  stroke-width: 2;
}

.picker-menu {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 0;
  z-index: 30;
  width: 300px;
  padding: 6px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-pop);
}

.picker-search {
  width: 100%;
  margin-bottom: 4px;
}

.picker-list {
  max-height: 260px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.picker-option {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 1px;
  padding: 7px 8px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}

.picker-option:hover,
.picker-option.active {
  background: var(--bg-hover);
  color: var(--text-main);
}

.option-name {
  font-size: 12.5px;
}

.option-hint {
  font-size: 11px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.picker-empty {
  margin: 8px;
  font-size: 12px;
  color: var(--text-muted);
}

.picker-foot {
  display: block;
  padding: 7px 8px 3px;
  margin-top: 4px;
  border-top: 1px solid var(--border-color);
  font-size: 12px;
  color: var(--text-muted);
}

.picker-foot:hover {
  color: var(--text-main);
}
</style>

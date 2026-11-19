<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import AgentPicker from './AgentPicker.vue'
import ModelSelector from './ModelSelector.vue'
import type { Agent } from '../types/api'

const props = defineProps<{
  agents: Agent[]
  agentId: number | null
  model: string
  input: string
  maxSteps: number | null
  running: boolean
}>()

const emit = defineEmits<{
  (e: 'update:agentId', value: number): void
  (e: 'update:model', value: string): void
  (e: 'update:input', value: string): void
  (e: 'update:maxSteps', value: number | null): void
  (e: 'change-model', value: string): void
  (e: 'send'): void
}>()

const textarea = ref<HTMLTextAreaElement | null>(null)

const hasText = computed(() => !!props.input.trim())
// 有文字且不在执行中，箭头变亮；为空时保持灰色禁用（是否选择了 Agent 由 send 时校验）
const canSend = computed(() => hasText.value && !props.running)

const selectedAgent = computed(
  () => props.agents.find((agent) => agent.id === props.agentId) ?? null,
)

// 留空不是“无限制”，而是使用该 Agent 配置的 max_steps
const stepsPlaceholder = computed(() =>
  selectedAgent.value ? `默认 ${selectedAgent.value.max_steps}` : '跟随 Agent',
)

const stepsTitle = computed(() =>
  selectedAgent.value
    ? `留空则使用「${selectedAgent.value.name}」配置的最大执行步数 ${selectedAgent.value.max_steps}（1~20）`
    : '留空则使用所选 Agent 配置的最大执行步数（1~20）',
)

function resize() {
  const element = textarea.value
  if (!element) return
  element.style.height = 'auto'
  element.style.height = `${Math.min(element.scrollHeight, 200)}px`
}

function onInput(event: Event) {
  emit('update:input', (event.target as HTMLTextAreaElement).value)
  resize()
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    if (canSend.value) emit('send')
  }
}

function onSteps(event: Event) {
  const value = (event.target as HTMLInputElement).value
  const parsed = value ? Number(value) : null
  emit('update:maxSteps', parsed != null && Number.isFinite(parsed) ? parsed : null)
}

function onModelSelect(value: string) {
  emit('update:model', value)
  emit('change-model', value)
}

function focus() {
  void nextTick(() => textarea.value?.focus())
}

defineExpose({ focus })
</script>

<template>
  <form class="composer" @submit.prevent="emit('send')">
    <div class="composer-top">
      <AgentPicker
        :agents="agents"
        :model-value="agentId"
        :disabled="running"
        @update:model-value="emit('update:agentId', $event)"
      />
      <ModelSelector
        :model-value="model"
        :disabled="running"
        @update:model-value="onModelSelect"
      />
      <label class="steps" :title="stepsTitle">
        <span class="steps-label">最大执行步数</span>
        <input
          type="number"
          min="1"
          max="20"
          :value="maxSteps ?? ''"
          :placeholder="stepsPlaceholder"
          :disabled="running"
          @input="onSteps"
        />
      </label>
    </div>

    <div class="composer-input-row">
      <textarea
        ref="textarea"
        class="composer-input"
        rows="1"
        maxlength="8000"
        :value="input"
        :disabled="running"
        placeholder="告诉Agent你想完成什么"
        @input="onInput"
        @keydown="onKeydown"
      ></textarea>

      <button class="send" type="submit" :disabled="!canSend" aria-label="发送">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5M6 11l6-6 6 6" /></svg>
      </button>
    </div>
  </form>
</template>

<style scoped>
.composer {
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 10px 12px 10px;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.composer:focus-within {
  border-color: rgba(77, 107, 254, 0.55);
  box-shadow: 0 0 0 3px rgba(77, 107, 254, 0.12);
}

.composer-top {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.steps {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 9px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-elevated);
  font-size: 12px;
  color: var(--text-muted);
  transition: border-color 0.15s ease;
}

.steps:hover,
.steps:focus-within {
  border-color: var(--border-strong);
}

.steps-label {
  color: var(--text-muted);
}

.steps input {
  width: 76px;
  height: 24px;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--text-main);
  font-size: 12px;
}

.steps input:focus-visible {
  outline: none;
}

.steps input::placeholder {
  color: var(--text-main);
  opacity: 1;
}

.composer-input-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
}

.composer-input {
  flex: 1;
  min-width: 0;
  min-height: 26px;
  max-height: 200px;
  padding: 4px 2px;
  border: none;
  background: transparent;
  color: var(--text-main);
  font-size: 14px;
  line-height: 1.6;
  resize: none;
  outline: none;
}

.composer-input:disabled {
  opacity: 0.6;
}

.send {
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 50%;
  background: var(--accent);
  color: #fff;
  cursor: pointer;
  transition: background 0.15s ease, opacity 0.15s ease;
}

.send:hover {
  background: var(--accent-hover);
}

.send:disabled {
  background: var(--bg-elevated);
  color: var(--text-muted);
  cursor: not-allowed;
}

.send svg {
  width: 15px;
  height: 15px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}
</style>

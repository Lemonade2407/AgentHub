<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, isRouteMissing } from '../api/http'
import type { ModelApiOption } from '../types/api'

interface Option {
  value: string
  label: string
  group: string
}

const props = defineProps<{
  modelValue: string
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

const FALLBACK_MODELS = ['deepseek/deepseek-chat', 'openai/gpt-4o-mini', 'qwen/qwen-plus']

const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const menuEl = ref<HTMLElement | null>(null)
const menuStyle = ref<Record<string, string>>({})
const listStyle = ref<Record<string, string>>({})
const open = ref(false)
const options = ref<Option[]>([])
const loaded = ref(false)
const unavailable = ref(false)

const MENU_WIDTH = 300
const MENU_MARGIN = 8
const MENU_GAP = 6

// 菜单挂到 body 上并使用 fixed 定位，避免被页面容器裁剪
function positionMenu() {
  const el = trigger.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const spaceBelow = window.innerHeight - rect.bottom - MENU_GAP - MENU_MARGIN
  const spaceAbove = rect.top - MENU_GAP - MENU_MARGIN
  const dropUp = spaceBelow < 200 && spaceAbove > spaceBelow
  const maxHeight = Math.max(160, Math.min(340, dropUp ? spaceAbove : spaceBelow))
  const left = Math.max(
    MENU_MARGIN,
    Math.min(rect.right - MENU_WIDTH, window.innerWidth - MENU_WIDTH - MENU_MARGIN),
  )
  menuStyle.value = {
    left: `${left}px`,
    maxHeight: `${maxHeight}px`,
    ...(dropUp
      ? { bottom: `${window.innerHeight - rect.top + MENU_GAP}px` }
      : { top: `${rect.bottom + MENU_GAP}px` }),
  }
  listStyle.value = { maxHeight: `${Math.max(80, maxHeight - 66)}px` }
}

const currentLabel = computed(() => {
  const match = options.value.find((option) => option.value === props.modelValue)
  return match?.label ?? (props.modelValue || '默认')
})

const groups = computed(() => {
  const map = new Map<string, Option[]>()
  for (const option of options.value) {
    const list = map.get(option.group) ?? []
    list.push(option)
    map.set(option.group, list)
  }
  return [...map.entries()].map(([group, items]) => ({ group, items }))
})

async function load() {
  try {
    const raw = await api.get<ModelApiOption[] | { items: ModelApiOption[] }>(
      '/api/model-apis/available',
    )
    const tree = Array.isArray(raw) ? raw : (raw.items ?? [])
    const items: Option[] = []
    for (const apiItem of tree) {
      for (const model of apiItem.models ?? []) {
        items.push({
          value: `${apiItem.provider}/${model.model_key}`,
          label: model.display_name || model.model_key,
          group: apiItem.name,
        })
      }
    }
    options.value = items
    unavailable.value = false
  } catch (error) {
    // 后端 WP-1.2 未就绪时回落 V1 的 provider/model 字符串
    unavailable.value = isRouteMissing(error)
    options.value = []
  } finally {
    if (!options.value.some((option) => option.value === props.modelValue) && props.modelValue) {
      options.value.unshift({ value: props.modelValue, label: props.modelValue, group: '当前模型' })
    }
    if (!options.value.length) {
      options.value = FALLBACK_MODELS.map((value) => ({
        value,
        label: value,
        group: '常用模型',
      }))
    }
    loaded.value = true
  }
}

function onDocumentClick(event: MouseEvent) {
  const target = event.target as Node
  if (root.value?.contains(target) || menuEl.value?.contains(target)) return
  close()
}

function close() {
  open.value = false
  document.removeEventListener('click', onDocumentClick)
  window.removeEventListener('resize', positionMenu)
  window.removeEventListener('scroll', positionMenu, true)
}

function toggle() {
  if (props.disabled) return
  if (open.value) {
    close()
    return
  }
  open.value = true
  document.addEventListener('click', onDocumentClick)
  window.addEventListener('resize', positionMenu)
  window.addEventListener('scroll', positionMenu, true)
  void nextTick(positionMenu)
}

function choose(option: Option) {
  emit('update:modelValue', option.value)
  close()
}

onMounted(load)
onBeforeUnmount(close)
</script>

<template>
  <div ref="root" class="model-picker">
    <button
      ref="trigger"
      class="model-trigger"
      type="button"
      :disabled="disabled"
      :title="modelValue"
      @click.stop="toggle"
    >
      <span class="model-caption">模型</span>
      <span class="model-value">{{ currentLabel }}</span>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
    </button>

    <Teleport to="body">
      <div v-if="open" ref="menuEl" class="model-menu" :style="menuStyle">
        <p v-if="unavailable" class="model-note">
          暂未获取到模型列表，可直接填写模型标识。
        </p>
        <div class="model-list" :style="listStyle">
          <template v-for="entry in groups" :key="entry.group">
            <p class="model-group">{{ entry.group }}</p>
            <button
              v-for="option in entry.items"
              :key="option.value"
              class="model-option"
              :class="{ active: option.value === modelValue }"
              type="button"
              @click="choose(option)"
            >
              <span class="model-option-label">{{ option.label }}</span>
              <span class="model-option-key">{{ option.value }}</span>
            </button>
          </template>
          <p v-if="!loaded" class="model-note">加载中…</p>
        </div>
        <router-link to="/settings/models" class="model-foot" @click="close">
          管理模型 API
        </router-link>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.model-picker {
  position: relative;
}

.model-trigger {
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

.model-trigger:hover {
  border-color: var(--border-strong);
}

.model-caption {
  color: var(--text-muted);
}

.model-value {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model-trigger svg {
  width: 12px;
  height: 12px;
  fill: none;
  stroke: var(--text-muted);
  stroke-width: 2;
}

.model-menu {
  position: fixed;
  z-index: 200;
  width: 300px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 6px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-pop);
}

.model-note {
  margin: 6px 8px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-muted);
}

.model-list {
  min-height: 0;
  overflow-y: auto;
}

.model-group {
  margin: 6px 8px 3px;
  font-size: 10.5px;
  color: var(--text-muted);
  letter-spacing: 0.4px;
}

.model-option {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 1px;
  padding: 6px 8px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}

.model-option:hover,
.model-option.active {
  background: var(--bg-hover);
  color: var(--text-main);
}

.model-option-label {
  font-size: 12.5px;
}

.model-option-key {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-muted);
}

.model-foot {
  display: block;
  padding: 7px 8px 3px;
  margin-top: 4px;
  border-top: 1px solid var(--border-color);
  font-size: 12px;
  color: var(--text-muted);
}

.model-foot:hover {
  color: var(--text-main);
}
</style>

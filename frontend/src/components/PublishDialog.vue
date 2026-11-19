<script setup lang="ts">
import { ref } from 'vue'
import { api, errorMessage, isRouteMissing } from '../api/http'
import { SKILL_CATEGORIES } from '../types/skill'

const props = defineProps<{
  agentId: number
  name: string
  description: string | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'published'): void
}>()

const form = ref({
  title: props.name,
  summary: props.description ?? '',
  category: 'general',
  version: '1.0.0',
})
const saving = ref(false)
const error = ref('')

async function submit() {
  error.value = ''
  if (!form.value.title.trim()) {
    error.value = '请填写标题'
    return
  }
  saving.value = true
  try {
    await api.post(`/api/agents/${props.agentId}/publish`, {
      title: form.value.title.trim(),
      summary: form.value.summary.trim(),
      category: form.value.category,
      version: form.value.version.trim() || '1.0.0',
    })
    emit('published')
  } catch (e) {
    error.value = isRouteMissing(e)
      ? '发布服务暂时不可用，请稍后重试。'
      : errorMessage(e, '发布失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="overlay" @click.self="emit('close')">
    <form class="modal" @submit.prevent="submit">
      <h3>发布到 Agent Center</h3>
      <p class="modal-desc">
        发布会生成固定快照，包含 Skill、工具依赖与 Prompt；密钥与请求头不会写入快照。
      </p>

      <label class="row">
        <span>标题</span>
        <input v-model="form.title" type="text" maxlength="64" required />
      </label>

      <label class="row">
        <span>简介</span>
        <input v-model="form.summary" type="text" maxlength="512" />
      </label>

      <div class="row two">
        <label>
          <span>分类</span>
          <select v-model="form.category">
            <option v-for="item in SKILL_CATEGORIES" :key="item.value" :value="item.value">
              {{ item.label }}
            </option>
          </select>
        </label>
        <label>
          <span>版本</span>
          <input v-model="form.version" type="text" maxlength="16" />
        </label>
      </div>

      <p v-if="error" class="error">{{ error }}</p>

      <div class="actions">
        <button class="btn" type="button" @click="emit('close')">取消</button>
        <button class="btn-primary" type="submit" :disabled="saving">
          {{ saving ? '发布中…' : '发布' }}
        </button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.modal h3 {
  margin: 0 0 4px;
  font-size: 16px;
}

.modal-desc {
  margin: 0 0 16px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-muted);
}

.row {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}

.row > span {
  font-size: 12.5px;
  color: var(--text-secondary);
}

.row.two {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.row.two > label {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
</style>

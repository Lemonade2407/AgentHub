<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api/http'

interface Me {
  id?: number
  email: string
  display_name: string
}

const me = ref<Me | null>(null)
const localMode = ref(false)
const loading = ref(true)

const initial = computed(() => (me.value?.display_name || me.value?.email || '?').trim().charAt(0).toUpperCase())

onMounted(async () => {
  try {
    me.value = await api.get<Me>('/api/auth/me')
  } catch {
    localMode.value = true
    me.value = { email: 'local@agenthub.local', display_name: 'Local' }
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <section class="page">
    <header class="page-header">
      <div>
        <h1 class="page-title">账号</h1>
      </div>
    </header>

    <p v-if="loading" class="muted">加载中…</p>

    <article v-if="me" class="card account-card">
      <div class="identity">
        <span class="avatar">{{ initial }}</span>
        <div class="identity-text">
          <strong>{{ me.display_name }}</strong>
          <span class="mono">{{ me.email }}</span>
        </div>
      </div>

      <dl class="kv">
        <dt>模式</dt>
        <dd>
          <span class="badge" :class="localMode ? 'archived' : 'on'">
            {{ localMode ? '本地模式' : '登录模式' }}
          </span>
        </dd>
      </dl>
    </article>
  </section>
</template>

<style scoped>
.account-card {
  display: flex;
  flex-direction: column;
  max-width: 520px;
  gap: 18px;
}

.identity {
  display: flex;
  align-items: center;
  gap: 12px;
}

.avatar {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--accent-soft);
  color: var(--accent-hover);
  font-size: 17px;
  font-weight: 600;
  flex-shrink: 0;
}

.identity-text {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.identity-text strong {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-main);
}

.kv {
  display: grid;
  grid-template-columns: 90px 1fr;
  gap: 8px 12px;
  margin: 0;
  font-size: 12.5px;
}

.kv dt {
  color: var(--text-muted);
}

.kv dd {
  margin: 0;
  color: var(--text-main);
}

.mono {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>

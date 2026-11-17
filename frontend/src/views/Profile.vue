<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, isRouteMissing } from '../api/http'

interface Me {
  id?: number
  email: string
  display_name: string
}

const me = ref<Me | null>(null)
const localMode = ref(false)
const loading = ref(true)
const offline = ref(false)

onMounted(async () => {
  try {
    me.value = await api.get<Me>('/api/auth/me')
  } catch (e) {
    localMode.value = true
    me.value = { email: 'local@agenthub.local', display_name: 'Local' }
    // 接口不存在（D 的 WP-1.1 未实现）或后端未启动时，都展示本地默认账号
    offline.value = !isRouteMissing(e)
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
    <p v-if="offline" class="muted offline-hint">
      后端未连接，当前展示本地默认账号；启动 FastAPI 后会自动读取真实用户。
    </p>

    <div v-if="me" class="grid">
      <article class="card">
        <h2>当前会话</h2>
        <dl class="kv">
          <dt>显示名</dt>
          <dd>{{ me.display_name }}</dd>
          <dt>邮箱</dt>
          <dd class="mono">{{ me.email }}</dd>
          <dt>模式</dt>
          <dd>
            <span class="badge" :class="localMode ? 'archived' : 'on'">
              {{ localMode ? '本地模式（AUTH_MODE=local）' : '登录模式' }}
            </span>
          </dd>
        </dl>
        <p class="muted note">
          账号接口（D：WP-1.1）未就绪时后端回落到内置 local 用户，保证 V1 演示脚本与本地联调可用。
        </p>
      </article>

      <article class="card">
        <h2>本地联调提示</h2>
        <ul class="tips">
          <li>未登录时所有资源归属 local 用户，可直接跑通工作台、Skills 与 MCP。</li>
          <li>
            需要演示“跨账号可见”时，可带请求头 <code>X-User-Email: other@example.com</code>
            访问后端，自动创建另一个账号。
          </li>
          <li>登录 / 注册 / 退出与会话 Cookie 由 D 在 WP-1.1 中接入。</li>
        </ul>
      </article>
    </div>
  </section>
</template>

<style scoped>
.grid {
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  align-items: start;
}

.card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.card h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
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
}

.note {
  margin: 0;
  font-size: 11.5px;
  line-height: 1.6;
}

.tips {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.offline-hint {
  margin-bottom: 12px;
  font-size: 12px;
}
</style>

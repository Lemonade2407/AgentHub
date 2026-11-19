<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, errorMessage, isRouteMissing } from '../api/http'
import type { InstallResult, PrecheckResult, Publication } from '../types/api'

const props = defineProps<{
  publication: Publication
  demo?: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'installed', agentId: number): void
}>()

const router = useRouter()
const precheck = ref<PrecheckResult | null>(null)
const loading = ref(true)
const error = ref('')
const demoFallback = ref(false)
const installing = ref(false)
const result = ref<InstallResult | null>(null)

const blockingMissing = computed(() => {
  const value = precheck.value
  if (!value) return false
  return (
    value.missing_skills.some((item) => item.required) ||
    value.missing_tools.some((item) => item.required)
  )
})

const canInstall = computed(() => {
  const value = precheck.value
  if (!value || value.already_installed) return false
  return value.can_install && !blockingMissing.value
})

function demoPrecheck(): PrecheckResult {
  const snapshot = props.publication.snapshot
  return {
    publication_id: props.publication.id,
    title: props.publication.title,
    can_install: false,
    already_installed: false,
    installed_agent_id: null,
    resolved_skills: 0,
    resolved_tools: 0,
    missing_skills: (snapshot.skills ?? []).map((skill) => ({
      slug: skill.slug,
      version: skill.version,
      params: skill.params ?? {},
      required: true,
      reason: '本地与公开广场均未找到匹配 Skill',
    })),
    missing_tools: (snapshot.tools ?? []).map((tool) => ({
      server_name: tool.server_name,
      remote_name: tool.remote_name,
      required: tool.required ?? true,
      reason: '本地未注册同名 MCP Server',
    })),
    warnings: ['当前为示例数据，无法执行安装。'],
    suggested_model: snapshot.suggested_model ?? null,
  }
}

async function load() {
  loading.value = true
  error.value = ''
  if (props.demo) {
    demoFallback.value = true
    precheck.value = demoPrecheck()
    loading.value = false
    return
  }
  try {
    precheck.value = await api.post<PrecheckResult>(
      `/api/agent-center/${props.publication.id}/precheck`,
    )
  } catch (e) {
    if (isRouteMissing(e)) {
      demoFallback.value = true
      precheck.value = demoPrecheck()
    } else {
      error.value = errorMessage(e, '预检失败')
    }
  } finally {
    loading.value = false
  }
}

async function install(confirmMissing: boolean) {
  if (!precheck.value || demoFallback.value) {
    error.value = '示例数据无法安装'
    return
  }
  installing.value = true
  error.value = ''
  try {
    result.value = await api.post<InstallResult>(
      `/api/agent-center/${props.publication.id}/install`,
      { confirm_missing: confirmMissing },
    )
  } catch (e) {
    error.value = errorMessage(e, '安装失败')
  } finally {
    installing.value = false
  }
}

function openInstalled() {
  const agentId = result.value?.agent_id ?? precheck.value?.installed_agent_id
  if (!agentId) return
  emit('installed', agentId)
  emit('close')
  router.push(`/agents/${agentId}?tab=model`)
}

onMounted(load)
</script>

<template>
  <div class="overlay" @click.self="emit('close')">
    <div class="modal precheck">
      <header class="modal-head">
        <div>
          <h3>安装前预检</h3>
          <p class="muted">{{ publication.title }} · v{{ publication.version }}</p>
        </div>
        <button class="close" type="button" aria-label="关闭" @click="emit('close')">×</button>
      </header>

      <p v-if="loading" class="muted">预检中…</p>
      <p v-if="error" class="error-box">{{ error }}</p>
      <p v-if="demoFallback" class="demo-hint">以下为示例缺失清单。</p>

      <template v-if="precheck && !loading">
        <div class="summary-row">
          <span class="badge" :class="precheck.already_installed ? 'archived' : canInstall ? 'on' : 'error'">
            {{
              precheck.already_installed
                ? '已安装过'
                : canInstall
                  ? '可以直接安装'
                  : blockingMissing
                    ? '存在必填依赖缺失'
                    : '可安装'
            }}
          </span>
          <span class="muted">已匹配 Skill {{ precheck.resolved_skills }}</span>
          <span class="muted">已匹配工具 {{ precheck.resolved_tools }}</span>
        </div>

        <section v-if="precheck.missing_skills.length" class="block">
          <h4>缺失 Skill</h4>
          <ul>
            <li v-for="item in precheck.missing_skills" :key="item.slug">
              <code>{{ item.slug }}</code> · v{{ item.version }}
              <span class="badge" :class="item.required ? 'error' : 'off'">
                {{ item.required ? '必填' : '可选' }}
              </span>
              <p class="reason">{{ item.reason }}</p>
            </li>
          </ul>
          <router-link to="/skills" class="link">去 Skills Center 安装或新建</router-link>
        </section>

        <section v-if="precheck.missing_tools.length" class="block">
          <h4>缺失 MCP Server</h4>
          <ul>
            <li v-for="item in precheck.missing_tools" :key="`${item.server_name}.${item.remote_name}`">
              <code>{{ item.server_name }}</code> / <code>{{ item.remote_name }}</code>
              <span class="badge" :class="item.required ? 'error' : 'off'">
                {{ item.required ? '必填' : '可选' }}
              </span>
              <p class="reason">{{ item.reason }}</p>
            </li>
          </ul>
          <router-link to="/mcp" class="link">去 MCP Hub 注册同名 Server</router-link>
        </section>

        <section v-if="precheck.suggested_model" class="block">
          <h4>建议模型</h4>
          <p class="muted">
            <code>{{ precheck.suggested_model.provider }}/{{ precheck.suggested_model.model_key }}</code>
            · 安装后需选择你自己的 Model API
          </p>
        </section>

        <section v-if="precheck.warnings.length" class="block">
          <h4>提示</h4>
          <ul>
            <li v-for="warning in precheck.warnings" :key="warning" class="reason">{{ warning }}</li>
          </ul>
        </section>

        <section v-if="result" class="block result-block">
          <h4>安装完成</h4>
          <p class="muted">新 Agent #{{ result.agent_id }} 已创建。</p>
          <ul v-if="result.next_steps.length">
            <li v-for="step in result.next_steps" :key="step">{{ step }}</li>
          </ul>
        </section>

        <p v-if="precheck.already_installed" class="muted">
          你已经安装过该 Agent，可直接打开副本继续编辑。
        </p>
      </template>

      <footer class="modal-foot">
        <button class="btn" type="button" @click="emit('close')">关闭</button>
        <span class="spacer"></span>
        <button
          v-if="result"
          class="btn-primary"
          type="button"
          @click="openInstalled"
        >
          打开 Agent 编辑器
        </button>
        <template v-else-if="precheck">
          <button
            v-if="precheck.already_installed && precheck.installed_agent_id"
            class="btn-primary"
            type="button"
            @click="openInstalled"
          >
            打开已安装副本
          </button>
          <button
            v-else-if="canInstall"
            class="btn-primary"
            type="button"
            :disabled="installing"
            @click="install(false)"
          >
            {{ installing ? '安装中…' : '安装' }}
          </button>
          <button
            v-else
            class="btn-primary"
            type="button"
            :disabled="installing || demoFallback"
            @click="install(true)"
          >
            {{ installing ? '安装中…' : '仍然安装（跳过缺失）' }}
          </button>
        </template>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.precheck {
  width: min(600px, calc(100vw - 32px));
}

.modal-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.modal-head h3 {
  margin: 0;
  font-size: 16px;
}

.modal-head p {
  margin: 2px 0 0;
  font-size: 12px;
}

.close {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text-muted);
  font-size: 18px;
  cursor: pointer;
}

.close:hover {
  background: var(--bg-hover);
  color: var(--text-main);
}

.demo-hint {
  margin: 8px 0;
  font-size: 12px;
  color: var(--warn);
}

.summary-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 10px 0;
  border-bottom: 1px solid var(--border-color);
  font-size: 12px;
}

.block {
  padding: 12px 0;
  border-bottom: 1px solid var(--border-color);
}

.block h4 {
  margin: 0 0 8px;
  font-size: 12.5px;
  color: var(--text-secondary);
}

.block ul {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12.5px;
}

.reason {
  margin: 2px 0 0;
  font-size: 11.5px;
  color: var(--text-muted);
}

.link {
  display: inline-block;
  margin-top: 8px;
  font-size: 12px;
}

.result-block {
  border-bottom: none;
  background: var(--success-soft);
  border-radius: var(--radius-sm);
  padding: 12px;
}

.modal-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
}

.spacer {
  flex: 1;
}
</style>

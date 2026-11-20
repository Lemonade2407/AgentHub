<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'

const props = withDefaults(
  defineProps<{
    code: string
    language?: string
  }>(),
  { language: '' },
)

const codeRef = ref<HTMLElement | null>(null)
const copied = ref(false)
let resetTimer: number | undefined

async function copyCode() {
  // 从 <code> 的 textContent 读取，确保复制的是纯代码，不含 HTML 标签
  const text = codeRef.value?.textContent ?? props.code
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true

    // 2 秒后恢复；连续点击时重置计时器，避免提前恢复
    if (resetTimer) window.clearTimeout(resetTimer)
    resetTimer = window.setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch (error) {
    console.error('复制代码失败：', error)
  }
}

onBeforeUnmount(() => {
  if (resetTimer) window.clearTimeout(resetTimer)
})
</script>

<template>
  <div class="code-block">
    <button
      class="code-copy"
      type="button"
      :aria-label="copied ? '已复制' : '复制代码'"
      @click="copyCode"
    >
      {{ copied ? '已复制！' : '复制代码' }}
    </button>

    <pre><code
      ref="codeRef"
      :class="language ? `language-${language}` : undefined"
    >{{ code }}</code></pre>
  </div>
</template>

<style scoped>
.code-block {
  position: relative;
  margin: 12px 0;
}

.code-copy {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 1;
  padding: 4px 10px;
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 6px;
  background: rgba(30, 41, 59, 0.92);
  color: #e2e8f0;
  font-family: inherit;
  font-size: 12px;
  line-height: 1.4;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s ease, border-color 0.15s ease;
}

.code-copy:hover {
  background: rgba(51, 65, 85, 0.98);
  border-color: rgba(255, 255, 255, 0.32);
}

.code-block pre {
  margin: 0;
  padding: 40px 16px 16px;
  overflow-x: auto;
  border-radius: 8px;
  background: #0f172a;
  color: #e2e8f0;
  font-family: 'JetBrains Mono', Consolas, Monaco, monospace;
  font-size: 13px;
  line-height: 1.65;
}

.code-block code {
  font-family: inherit;
  white-space: pre;
}
</style>

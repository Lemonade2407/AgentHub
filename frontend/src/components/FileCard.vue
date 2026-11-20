<script setup lang="ts">
import { computed, ref } from 'vue'
import { loadDocxHtml } from '../utils/docx-preview'

const props = defineProps<{ url: string }>()

const previewOpen = ref(false)
const docHtml = ref('')
const docLoading = ref(false)
const docError = ref('')

const filename = computed(() => {
  const clean = props.url.split('?')[0].split('#')[0]
  const raw = clean.split('/').pop() || '文件'
  try {
    return decodeURIComponent(raw)
  } catch {
    return raw
  }
})

const isPdf = computed(() => filename.value.toLowerCase().endsWith('.pdf'))
const isWord = computed(() => filename.value.toLowerCase().endsWith('.docx'))
const kindLabel = computed(() => (isPdf.value ? 'PDF' : isWord.value ? 'Word' : '文件'))

async function openPreview() {
  previewOpen.value = true
  if (!isWord.value) return

  docLoading.value = true
  docHtml.value = ''
  docError.value = ''
  try {
    docHtml.value = await loadDocxHtml(props.url)
  } catch (e) {
    docError.value = e instanceof Error ? e.message : 'Word 预览加载失败'
  } finally {
    docLoading.value = false
  }
}
</script>

<template>
  <div class="file-card">
    <div class="file-main">
      <span class="file-icon" :class="{ pdf: isPdf, word: isWord }">
        {{ isPdf ? 'PDF' : 'W' }}
      </span>
      <div class="file-info">
        <span class="file-name" :title="filename">{{ filename }}</span>
        <span class="file-kind">{{ kindLabel }} 文件</span>
      </div>
    </div>

    <div class="file-actions">
      <button class="file-btn" type="button" @click="openPreview">预览</button>
      <a class="file-btn primary" :href="url" :download="filename">下载</a>
    </div>

    <div v-if="previewOpen" class="file-preview-overlay" @click.self="previewOpen = false">
      <div class="file-preview-modal">
        <header class="file-preview-head">
          <span class="file-preview-title">{{ filename }}</span>
          <div class="file-preview-ops">
            <a class="file-btn" :href="url" :download="filename">下载</a>
            <button class="file-btn" type="button" @click="previewOpen = false">关闭</button>
          </div>
        </header>

        <iframe v-if="isPdf" :src="url" title="PDF 预览"></iframe>

        <div v-else-if="isWord" class="file-preview-docx">
          <p v-if="docLoading" class="file-preview-tip">Word 预览加载中…</p>
          <div v-else-if="docError" class="file-preview-tip">
            {{ docError }}，请下载后查看。
          </div>
          <div v-else class="docx-content" v-html="docHtml"></div>
        </div>

        <div v-else class="file-preview-tip">该文件暂不支持在线预览。</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.file-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 10px 0;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--bg-elevated);
}

.file-main {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.file-icon {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  font-size: 10.5px;
  font-weight: 700;
}

.file-icon.pdf {
  color: #dc2626;
  border-color: rgba(220, 38, 38, 0.35);
  background: rgba(220, 38, 38, 0.08);
}

.file-icon.word {
  color: #2563eb;
  border-color: rgba(37, 99, 235, 0.35);
  background: rgba(37, 99, 235, 0.08);
}

.file-info {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.file-name {
  font-size: 12.5px;
  color: var(--text-main);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-kind {
  font-size: 11px;
  color: var(--text-muted);
}

.file-actions,
.file-preview-ops {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.file-btn {
  padding: 4px 10px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-panel);
  color: var(--text-secondary);
  font-family: inherit;
  font-size: 12px;
  line-height: 1.5;
  cursor: pointer;
  text-decoration: none;
}

.file-btn:hover {
  border-color: var(--border-strong);
  color: var(--text-main);
}

.file-btn.primary {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--text-main);
}

.file-preview-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
  background: rgba(0, 0, 0, 0.55);
}

.file-preview-modal {
  width: min(1000px, 92vw);
  height: min(820px, 88vh);
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  overflow: hidden;
  box-shadow: var(--shadow-pop);
}

.file-preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-color);
}

.file-preview-title {
  font-size: 12.5px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-preview-modal iframe {
  flex: 1;
  width: 100%;
  border: none;
  background: #fff;
}

.file-preview-tip {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  color: var(--text-muted);
  font-size: 13px;
}

.file-preview-docx {
  flex: 1;
  overflow-y: auto;
  background: #fff;
}

.docx-content {
  padding: 28px 36px;
  color: #1f2937;
  font-family: '宋体', 'Songti SC', serif;
  font-size: 14px;
  line-height: 1.8;
}

.docx-content :deep(h1) {
  margin: 18px 0 8px;
  font-family: '黑体', 'Heiti SC', sans-serif;
  font-size: 18px;
  font-weight: 700;
}

.docx-content :deep(h2) {
  margin: 16px 0 6px;
  font-size: 16px;
  font-weight: 700;
}

.docx-content :deep(h3) {
  margin: 14px 0 6px;
  font-size: 15px;
  font-weight: 700;
}

.docx-content :deep(p) {
  margin: 8px 0;
  text-indent: 2em;
}

.docx-content :deep(ul),
.docx-content :deep(ol) {
  margin: 8px 0;
  padding-left: 28px;
}

.docx-content :deep(li) {
  margin: 4px 0;
}

.docx-content :deep(table) {
  width: 100%;
  margin: 12px 0;
  border-collapse: collapse;
}

.docx-content :deep(th),
.docx-content :deep(td) {
  padding: 6px 8px;
  border: 1px solid #d1d5db;
  text-align: left;
}

.docx-content :deep(a) {
  color: #2563eb;
}
</style>

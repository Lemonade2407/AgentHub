<script setup lang="ts">
import { computed } from 'vue'
import CodeBlock from './CodeBlock.vue'
import FileCard from './FileCard.vue'

const props = defineProps<{ content: string }>()

interface TextSegment {
  type: 'text'
  value: string
}

interface CodeSegment {
  type: 'code'
  language: string
  code: string
}

interface FileSegment {
  type: 'file'
  url: string
}

type Segment = TextSegment | CodeSegment | FileSegment

const FENCE_RE = /```([^\n`]*)\n([\s\S]*?)```/g

// 识别裸链接与 Markdown 链接中的 Agent 文件地址（DOCX / PDF）
const FILE_URL_RE =
  /\[[^\]]*\]\(\s*(\/api\/agents\/[^\s)]+?\.(?:docx|pdf))\s*\)|(\/api\/agents\/[^\s)）\]】<>"'，。；、]+?\.(?:docx|pdf))/gi

function textSegments(value: string): Segment[] {
  const result: Segment[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null

  FILE_URL_RE.lastIndex = 0
  while ((match = FILE_URL_RE.exec(value)) !== null) {
    const url = match[1] || match[2]
    if (match.index > lastIndex) {
      result.push({ type: 'text', value: value.slice(lastIndex, match.index) })
    }
    result.push({ type: 'file', url })
    lastIndex = match.index + match[0].length
  }

  if (lastIndex < value.length) {
    result.push({ type: 'text', value: value.slice(lastIndex) })
  }
  return result
}

const segments = computed<Segment[]>(() => {
  const result: Segment[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null

  FENCE_RE.lastIndex = 0
  while ((match = FENCE_RE.exec(props.content)) !== null) {
    if (match.index > lastIndex) {
      result.push(...textSegments(props.content.slice(lastIndex, match.index)))
    }

    result.push({
      type: 'code',
      language: match[1].trim(),
      code: match[2].replace(/\n$/, ''),
    })

    lastIndex = match.index + match[0].length
  }

  if (lastIndex < props.content.length) {
    result.push(...textSegments(props.content.slice(lastIndex)))
  }

  return result
})
</script>

<template>
  <div class="markdown-message">
    <template v-for="(segment, index) in segments" :key="index">
      <CodeBlock
        v-if="segment.type === 'code'"
        :code="segment.code"
        :language="segment.language"
      />
      <FileCard v-else-if="segment.type === 'file'" :url="segment.url" />
      <div v-else class="text">{{ segment.value }}</div>
    </template>
  </div>
</template>

<style scoped>
.markdown-message {
  font-size: 13.5px;
  line-height: 1.8;
  color: var(--text-main);
  word-break: break-word;
}

.text {
  white-space: pre-wrap;
}
</style>

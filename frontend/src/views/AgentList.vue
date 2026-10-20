<script setup lang="ts">
// Agent 列表页（C 负责）
// 后续接接口：GET /api/agents（分页），见 AgentHub_接口契约文档.md §4
// 骨架阶段先放静态示例数据，不发起真实请求。
const placeholderAgents = [
  { id: 1, name: '示例 Agent', model: 'deepseek-chat', max_steps: 10, enabled: true },
]
</script>

<template>
  <section class="page">
    <h1>Agent 列表</h1>
    <p>对应接口：<code>GET /api/agents</code>（分页结构见契约文档 §1.3）</p>
    <ul>
      <li v-for="a in placeholderAgents" :key="a.id">
        #{{ a.id }} {{ a.name }} · {{ a.model }} · max_steps={{ a.max_steps }}
      </li>
    </ul>
  </section>
</template>

<script setup lang="ts">
// Agent 编辑器（C 负责）
// 后续接接口：GET /api/agents/{id} / POST /api/agents / PUT /api/agents/{id}
// 骨架阶段暂不实现表单。
</script>

<template>
  <section class="page">
    <h1>Agent 编辑器</h1>
    <p>
      对应接口：<code>GET /api/agents/{id}</code>、<code>POST /api/agents</code>、
      <code>PUT /api/agents/{id}</code>（见契约文档 §4）
    </p>
    <p class="muted">配置项：模型、System Prompt、最大执行步数、绑定 MCP 工具。</p>
  </section>
</template>

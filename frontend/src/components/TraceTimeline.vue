<script setup lang="ts">
// TraceTimeline（C 负责）：消费 SSE TraceEvent 流，按时间轴渲染执行过程
// 事件契约见 AgentHub_接口契约文档.md §5（event: trace / run_finished）
// 骨架阶段只渲染静态占位。
</script>

<template>
  <section class="trace">
    <h2>Execution Trace</h2>
    <p class="muted">LLM 调用 / Tool Calling / MCP 执行 / Observation / 状态变化 将在此按时间轴展示。</p>
  </section>
</template>

<style scoped>
.trace {
  margin-top: 16px;
  padding: 16px;
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 8px;
}

.trace h2 {
  font-size: 16px;
  margin: 0 0 8px;
}

.muted {
  color: var(--text-muted);
}
</style>

<template>
  <section class="page">
    <h1>Playground</h1>
    <p>
      对应接口：<code>POST /api/agents/{id}/runs</code>，通过 SSE 实时接收 Trace 事件
      （<code>event: trace</code> / <code>event: run_finished</code>，见契约文档 §4、§5）
    </p>
    <p class="muted">骨架阶段仅展示布局占位，后续接入输入框、运行按钮与 TraceTimeline。</p>
  </section>
</template>

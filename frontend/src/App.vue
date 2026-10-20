<script setup lang="ts">
const navItems = [
  { path: '/agents', label: 'Agent 列表' },
  { path: '/agents/1', label: 'Agent 编辑器' },
  { path: '/mcp', label: 'MCP Center' },
  { path: '/playground', label: 'Playground' },
]
</script>

<template>
  <div class="layout">
    <nav class="sidebar">
      <div class="brand">AgentHub</div>
      <router-link v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
        {{ item.label }}
      </router-link>
    </nav>
    <main class="content">
      <router-view />
    </main>
  </div>
</template>

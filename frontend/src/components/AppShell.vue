<script setup lang="ts">
import { ui, closeSidebar } from '../stores/ui'
import SidebarNav from './SidebarNav.vue'
import TopBar from './TopBar.vue'
import CommandPalette from './CommandPalette.vue'

defineProps<{
  /** 对话页需要自行控制滚动，去掉内容区 padding 与 overflow */
  flush?: boolean
}>()
</script>

<template>
  <div class="shell" :class="{ 'sidebar-open': ui.sidebarOpen }">
    <SidebarNav />

    <div class="shell-main">
      <TopBar />
      <main class="shell-content" :class="{ flush }">
        <slot />
      </main>
    </div>

    <div v-if="ui.sidebarOpen" class="scrim" @click="closeSidebar"></div>
    <CommandPalette />

    <!-- 移动端底部标签栏（§6.4 响应式 <768） -->
    <nav class="mobile-tabs">
      <router-link to="/chat" class="mobile-tab">工作台</router-link>
      <router-link to="/agents" class="mobile-tab">Agents</router-link>
      <router-link to="/skills" class="mobile-tab">Skills</router-link>
      <router-link to="/agent-center" class="mobile-tab">广场</router-link>
      <button class="mobile-tab" type="button" @click="ui.sidebarOpen = true">更多</button>
    </nav>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
  background: var(--bg-base);
}

.shell-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.shell-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
}

.shell-content.flush {
  overflow: hidden;
}

.scrim {
  display: none;
}

.mobile-tabs {
  display: none;
}

@media (max-width: 1024px) {
  .scrim {
    display: block;
    position: fixed;
    inset: 0;
    background: rgba(5, 7, 10, 0.6);
    z-index: 40;
  }
}

@media (max-width: 768px) {
  .shell {
    flex-direction: column;
  }

  .shell-content {
    padding-bottom: 56px;
  }

  .mobile-tabs {
    display: flex;
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    height: 52px;
    background: var(--bg-panel);
    border-top: 1px solid var(--border-color);
    z-index: 45;
  }

  .mobile-tab {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    border: none;
    background: transparent;
    color: var(--text-muted);
    font-size: 12px;
    font-family: inherit;
    text-decoration: none;
    cursor: pointer;
  }

  .mobile-tab.router-link-active {
    color: var(--accent-hover);
  }
}
</style>

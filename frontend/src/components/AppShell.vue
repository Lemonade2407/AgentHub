<script setup lang="ts">
import { ui } from '../stores/ui'
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

    <CommandPalette />

    <Transition name="global-toast">
      <div v-if="ui.notice" class="global-toast">{{ ui.notice }}</div>
    </Transition>
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

/* 侧栏与工作台并排：展开时仍可直接操作工作台，不产生遮罩 */
.shell:not(.sidebar-open) .sidebar {
  display: none;
}

.global-toast {
  position: fixed;
  left: 50%;
  bottom: 36px;
  z-index: 3000;
  transform: translateX(-50%);
  padding: 8px 18px;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  background: var(--bg-elevated);
  color: var(--text-main);
  font-size: 12.5px;
  box-shadow: var(--shadow-pop);
}

.global-toast-enter-active,
.global-toast-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.global-toast-enter-from,
.global-toast-leave-to {
  opacity: 0;
  transform: translate(-50%, 8px);
}
</style>

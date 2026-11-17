<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { openPalette, ui } from '../stores/ui'

const route = useRoute()
const title = computed(() => (route.meta.title as string | undefined) ?? 'AgentHub')
</script>

<template>
  <header class="topbar">
    <button class="hamburger" type="button" aria-label="打开导航" @click="ui.sidebarOpen = true">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 7h16M4 12h16M4 17h16" />
      </svg>
    </button>

    <div class="crumb">
      <span class="crumb-root">AgentHub</span>
      <span class="crumb-sep">/</span>
      <span>{{ title }}</span>
    </div>

    <button class="search-trigger" type="button" @click="openPalette">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-3.2-3.2" />
      </svg>
      <span class="search-text">搜索 Agent / Skill / 工具</span>
      <kbd>Ctrl K</kbd>
    </button>

    <div class="top-actions">
      <span class="mode-chip"><i></i>本地模式</span>
      <router-link to="/settings/profile" class="avatar" aria-label="账号">L</router-link>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  gap: 14px;
  height: 56px;
  flex-shrink: 0;
  padding: 0 20px;
  border-bottom: 1px solid var(--border-color);
  background: rgba(15, 17, 21, 0.82);
  backdrop-filter: blur(8px);
}

.hamburger {
  display: none;
  width: 32px;
  height: 32px;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}

.hamburger svg {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
}

.crumb {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-main);
  white-space: nowrap;
}

.crumb-root {
  color: var(--text-muted);
}

.crumb-sep {
  color: var(--text-muted);
}

.search-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  width: min(420px, 40vw);
  height: 34px;
  margin: 0 auto;
  padding: 0 10px;
  border: 1px solid var(--border-color);
  border-radius: 9px;
  background: var(--bg-input);
  color: var(--text-muted);
  font-family: inherit;
  font-size: 12.5px;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.search-trigger:hover {
  border-color: var(--border-strong);
  background: var(--bg-elevated);
}

.search-trigger svg {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
}

.search-text {
  flex: 1;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

kbd {
  padding: 0 5px;
  border: 1px solid var(--border-color);
  border-radius: 5px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 16px;
}

.top-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.mode-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 9px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  color: var(--text-muted);
  font-size: 11.5px;
}

.mode-chip i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--success);
}

.avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--accent-soft);
  color: var(--accent-hover);
  font-size: 12px;
  font-weight: 600;
}

@media (max-width: 1024px) {
  .hamburger {
    display: inline-flex;
  }

  .crumb {
    display: none;
  }

  .search-trigger {
    width: auto;
    flex: 1;
  }
}

@media (max-width: 768px) {
  .topbar {
    padding: 0 12px;
    gap: 8px;
  }

  .search-text {
    display: none;
  }

  .search-trigger {
    justify-content: center;
    width: 34px;
    flex: none;
    margin: 0;
    padding: 0;
  }

  .search-trigger kbd {
    display: none;
  }

  .mode-chip {
    display: none;
  }
}
</style>

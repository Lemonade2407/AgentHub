<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from './components/AppShell.vue'
import { ui } from './stores/ui'

const route = useRoute()
const isChat = computed(() => route.name === 'chat')

function onKeydown(event: KeyboardEvent) {
  const meta = event.metaKey || event.ctrlKey
  if (meta && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    ui.paletteOpen = !ui.paletteOpen
  }
  if (event.key === 'Escape') {
    ui.paletteOpen = false
    ui.sidebarOpen = false
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <AppShell :flush="isChat">
    <router-view />
  </AppShell>
</template>

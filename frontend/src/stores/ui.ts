import { reactive } from 'vue'

/** 全局壳的轻量 UI 状态（无需引入状态管理库）。 */
export const ui = reactive({
  sidebarOpen: false,
  paletteOpen: false,
})

export function closeSidebar(): void {
  ui.sidebarOpen = false
}

export function openPalette(): void {
  ui.paletteOpen = true
}

export function closePalette(): void {
  ui.paletteOpen = false
}

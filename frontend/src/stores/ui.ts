import { reactive } from 'vue'

/** 全局壳的轻量 UI 状态（无需引入状态管理库）。 */
export const ui = reactive({
  // 左侧工作栏默认展开；点击顶部按钮再收起
  sidebarOpen: true,
  paletteOpen: false,
  // 跨页面轻提示（例如保存成功后跳转回列表）
  notice: '',
})

let noticeTimer: number | undefined

export function showNotice(text: string, duration = 2600): void {
  ui.notice = text
  if (noticeTimer) window.clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => {
    ui.notice = ''
  }, duration)
}

export function closeSidebar(): void {
  ui.sidebarOpen = false
}

export function openPalette(): void {
  ui.paletteOpen = true
}

export function closePalette(): void {
  ui.paletteOpen = false
}

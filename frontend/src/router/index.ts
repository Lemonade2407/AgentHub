import { createRouter, createWebHistory } from 'vue-router'
import AgentList from '../views/AgentList.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    // 工作台：对话优先，runId 可为空（§6.2）
    { path: '/', redirect: '/chat' },
    {
      path: '/chat/:runId?',
      name: 'chat',
      component: () => import('../views/Workbench.vue'),
      meta: { title: '工作台' },
    },
    {
      path: '/agents',
      name: 'agents',
      component: AgentList,
      meta: { title: 'Agents' },
    },
    {
      path: '/agents/:id',
      name: 'agent-editor',
      component: () => import('../views/AgentEditor.vue'),
      meta: { title: 'Agent 编辑器' },
    },
    {
      path: '/mcp',
      name: 'mcp-center',
      component: () => import('../views/McpCenter.vue'),
      meta: { title: 'MCP Hub' },
    },
    {
      path: '/skills',
      name: 'skills-center',
      component: () => import('../views/SkillsCenter.vue'),
      meta: { title: 'Skills Center' },
    },
    {
      path: '/skills/:id',
      name: 'skill-editor',
      component: () => import('../views/SkillEditor.vue'),
      meta: { title: 'Skill 编辑器' },
    },
    {
      path: '/agent-center',
      name: 'agent-center',
      component: () => import('../views/AgentCenter.vue'),
      meta: { title: 'Agent Center' },
    },
    {
      path: '/agent-center/:id',
      name: 'publication-detail',
      component: () => import('../views/PublicationDetail.vue'),
      meta: { title: '发布详情' },
    },
    {
      path: '/settings/models',
      name: 'model-settings',
      component: () => import('../views/ModelSettings.vue'),
      meta: { title: '模型 API' },
    },
    {
      path: '/settings/models/new',
      name: 'model-api-new',
      component: () => import('../views/ModelApiEditor.vue'),
      meta: { title: '新建模型 API' },
    },
    {
      path: '/settings/models/:id',
      name: 'model-api-editor',
      component: () => import('../views/ModelApiEditor.vue'),
      meta: { title: '模型 API 编辑器' },
    },
    {
      path: '/settings/profile',
      name: 'profile',
      component: () => import('../views/Profile.vue'),
      meta: { title: '账号' },
    },
    // V1 的 Playground 并入工作台
    { path: '/playground', redirect: '/chat' },
    { path: '/:pathMatch(.*)*', redirect: '/chat' },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

export default router

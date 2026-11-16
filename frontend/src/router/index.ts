import { createRouter, createWebHistory } from 'vue-router'
import AgentList from '../views/AgentList.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/agents' },
    { path: '/agents', name: 'agents', component: AgentList },
    {
      path: '/agents/:id',
      name: 'agent-editor',
      component: () => import('../views/AgentEditor.vue'),
    },
    {
      path: '/mcp',
      name: 'mcp-center',
      component: () => import('../views/McpCenter.vue'),
    },
    {
      path: '/skills',
      name: 'skills-center',
      component: () => import('../views/SkillsCenter.vue'),
    },
    {
      path: '/skills/:id',
      name: 'skill-editor',
      component: () => import('../views/SkillEditor.vue'),
    },
    {
      path: '/playground',
      name: 'playground',
      component: () => import('../views/Playground.vue'),
    },
  ],
})

export default router

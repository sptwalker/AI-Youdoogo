/** 路由：/login 公开，其余经 RequireAuth 守卫（无 token 跳登录）。 */
import { createBrowserRouter } from 'react-router-dom'
import RequireAuth from './components/RequireAuth'
import AppLayout from './layouts/AppLayout'

export const router = createBrowserRouter([
  { path: '/login', lazy: async () => ({ Component: (await import('./pages/Login')).default }) },
  {
    path: '/',
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    children: [
      { index: true, lazy: async () => ({ Component: (await import('./pages/Dashboard')).default }) },
      { path: 'knowledge', lazy: async () => ({ Component: (await import('./pages/Knowledge')).default }) },
      { path: 'ops-board', lazy: async () => ({ Component: (await import('./pages/OpsBoard')).default }) },
      { path: 'agents', lazy: async () => ({ Component: (await import('./pages/Agents')).default }) },
      { path: 'tasks', lazy: async () => ({ Component: (await import('./pages/Tasks')).default }) },
      { path: 'proposals', lazy: async () => ({ Component: (await import('./pages/Proposals')).default }) },
      { path: 'meetings', lazy: async () => ({ Component: (await import('./pages/Meetings')).default }) },
      { path: 'discussion', lazy: async () => ({ Component: (await import('./pages/Discussion')).default }) },
      { path: 'org', lazy: async () => ({ Component: (await import('./pages/OrgAdmin')).default }) },
      { path: 'users', lazy: async () => ({ Component: (await import('./pages/Users')).default }) },
      { path: 'knowledge-bases', lazy: async () => ({ Component: (await import('./pages/KnowledgeBases')).default }) },
      { path: 'data-sources', lazy: async () => ({ Component: (await import('./pages/DataSources')).default }) },
      { path: 'semantic-terms', lazy: async () => ({ Component: (await import('./pages/SemanticTerms')).default }) },
      { path: 'ai-providers', lazy: async () => ({ Component: (await import('./pages/AiProviders')).default }) },
      { path: 'system-config', lazy: async () => ({ Component: (await import('./pages/SystemConfig')).default }) },
      { path: 'audit-log', lazy: async () => ({ Component: (await import('./pages/AuditLog')).default }) },
    ],
  },
])

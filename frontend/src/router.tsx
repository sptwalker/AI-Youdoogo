/** 路由：/login 公开，其余经 RequireAuth 守卫（无 token 跳登录）。 */
import { createBrowserRouter } from 'react-router-dom'
import RequireAuth from './components/RequireAuth'
import AppLayout from './layouts/AppLayout'
import RouteErrorPage from './pages/RouteErrorPage'

const ADMIN_ONLY = { roles: ['admin'] as const }

export const router = createBrowserRouter([
  {
    path: '/login',
    errorElement: <RouteErrorPage />,
    lazy: async () => ({ Component: (await import('./pages/Login')).default }),
  },
  {
    path: '/',
    errorElement: <RouteErrorPage />,
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
      { path: 'org', handle: ADMIN_ONLY, lazy: async () => ({ Component: (await import('./pages/OrgAdmin')).default }) },
      { path: 'users', handle: ADMIN_ONLY, lazy: async () => ({ Component: (await import('./pages/Users')).default }) },
      { path: 'knowledge-bases', handle: ADMIN_ONLY, lazy: async () => ({ Component: (await import('./pages/KnowledgeBases')).default }) },
      { path: 'data-sources', handle: ADMIN_ONLY, lazy: async () => ({ Component: (await import('./pages/DataSources')).default }) },
      { path: 'semantic-terms', handle: ADMIN_ONLY, lazy: async () => ({ Component: (await import('./pages/SemanticTerms')).default }) },
      { path: 'ai-providers', handle: ADMIN_ONLY, lazy: async () => ({ Component: (await import('./pages/AiProviders')).default }) },
      { path: 'system-config', handle: ADMIN_ONLY, lazy: async () => ({ Component: (await import('./pages/SystemConfig')).default }) },
      { path: 'audit-log', handle: ADMIN_ONLY, lazy: async () => ({ Component: (await import('./pages/AuditLog')).default }) },
      { path: '*', lazy: async () => ({ Component: (await import('./pages/NotFound')).default }) },
    ],
  },
])

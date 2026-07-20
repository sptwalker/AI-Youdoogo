/** 路由：/login 公开，其余经 RequireAuth 守卫（无 token 跳登录）。 */
import { createBrowserRouter } from 'react-router-dom'
import RequireAuth from './components/RequireAuth'
import AppLayout from './layouts/AppLayout'
import Agents from './pages/Agents'
import AiProviders from './pages/AiProviders'
import AuditLog from './pages/AuditLog'
import Dashboard from './pages/Dashboard'
import DataSources from './pages/DataSources'
import Discussion from './pages/Discussion'
import Knowledge from './pages/Knowledge'
import KnowledgeBases from './pages/KnowledgeBases'
import Login from './pages/Login'
import Meetings from './pages/Meetings'
import OpsBoard from './pages/OpsBoard'
import OrgAdmin from './pages/OrgAdmin'
import Proposals from './pages/Proposals'
import SemanticTerms from './pages/SemanticTerms'
import SystemConfig from './pages/SystemConfig'
import Tasks from './pages/Tasks'
import Users from './pages/Users'

export const router = createBrowserRouter([
  { path: '/login', element: <Login /> },
  {
    path: '/',
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'knowledge', element: <Knowledge /> },
      { path: 'ops-board', element: <OpsBoard /> },
      { path: 'agents', element: <Agents /> },
      { path: 'tasks', element: <Tasks /> },
      { path: 'proposals', element: <Proposals /> },
      { path: 'meetings', element: <Meetings /> },
      { path: 'discussion', element: <Discussion /> },
      { path: 'org', element: <OrgAdmin /> },
      { path: 'users', element: <Users /> },
      { path: 'knowledge-bases', element: <KnowledgeBases /> },
      { path: 'data-sources', element: <DataSources /> },
      { path: 'semantic-terms', element: <SemanticTerms /> },
      { path: 'ai-providers', element: <AiProviders /> },
      { path: 'system-config', element: <SystemConfig /> },
      { path: 'audit-log', element: <AuditLog /> },
    ],
  },
])

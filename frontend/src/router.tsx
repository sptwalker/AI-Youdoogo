/** 路由：/login 公开，其余经 RequireAuth 守卫（无 token 跳登录）。 */
import type { ReactElement } from 'react'
import { createBrowserRouter, Navigate } from 'react-router-dom'
import { TOKEN_KEY } from './api/client'
import AppLayout from './layouts/AppLayout'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import Users from './pages/Users'

function RequireAuth({ children }: { children: ReactElement }) {
  if (!localStorage.getItem(TOKEN_KEY)) return <Navigate to="/login" replace />
  return children
}

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
      { path: 'users', element: <Users /> },
    ],
  },
])

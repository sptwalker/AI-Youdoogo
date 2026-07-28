/** Route guard that preserves the intended page for either login method. */
import type { ReactElement } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { loginRedirectPath, TOKEN_KEY } from '../api/http'

export default function RequireAuth({ children }: { children: ReactElement }) {
  const location = useLocation()
  if (localStorage.getItem(TOKEN_KEY)) return children

  return <Navigate to={loginRedirectPath(location) ?? '/login'} replace />
}

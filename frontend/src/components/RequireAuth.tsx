/** Route guard that preserves the intended page for either login method. */
import type { ReactElement } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { TOKEN_KEY } from '../api/client'

export default function RequireAuth({ children }: { children: ReactElement }) {
  const location = useLocation()
  if (localStorage.getItem(TOKEN_KEY)) return children

  const returnTo = `${location.pathname}${location.search}`
  const query = new URLSearchParams({ return_to: returnTo })
  return <Navigate to={`/login?${query.toString()}`} replace />
}

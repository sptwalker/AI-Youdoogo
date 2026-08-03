import type { UserInfo } from '../api/auth'

export type RoleCode = UserInfo['role_code']

interface RouteAccessHandle {
  roles?: readonly RoleCode[]
}

function routeAccessHandle(value: unknown): RouteAccessHandle | null | undefined {
  if (value === undefined || value === null) return undefined
  if (typeof value !== 'object') return null
  const roles = (value as { roles?: unknown }).roles
  if (roles === undefined) return {}
  if (!Array.isArray(roles) || !roles.every((role) => (
    role === 'admin' || role === 'executive' || role === 'member'
  ))) return null
  return { roles }
}

export function routeAllowsRole(role: RoleCode, handles: readonly unknown[]): boolean {
  for (const rawHandle of handles) {
    const handle = routeAccessHandle(rawHandle)
    if (handle === null) return false
    if (handle?.roles && !handle.roles.includes(role)) return false
  }
  return true
}

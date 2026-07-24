import type { UserInfo } from '../api/auth'

type RoleCode = UserInfo['role_code'] | undefined

export function hasManagerRole(roleCode: RoleCode): boolean {
  return roleCode === 'admin' || roleCode === 'executive'
}

export function hasAdminRole(roleCode: RoleCode): boolean {
  return roleCode === 'admin'
}

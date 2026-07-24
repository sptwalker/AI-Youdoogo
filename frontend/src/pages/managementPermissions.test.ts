import { describe, expect, it } from 'vitest'
import { hasAdminRole, hasManagerRole } from './managementPermissions'

describe('management page permissions', () => {
  it('matches manager-only backend endpoints', () => {
    expect(hasManagerRole('admin')).toBe(true)
    expect(hasManagerRole('executive')).toBe(true)
    expect(hasManagerRole('member')).toBe(false)
    expect(hasManagerRole(undefined)).toBe(false)
  })

  it('matches admin-only agent configuration endpoints', () => {
    expect(hasAdminRole('admin')).toBe(true)
    expect(hasAdminRole('executive')).toBe(false)
    expect(hasAdminRole('member')).toBe(false)
  })
})

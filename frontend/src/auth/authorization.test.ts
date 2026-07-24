import { describe, expect, it } from 'vitest'
import { routeAllowsRole } from './authorization'

describe('route authorization', () => {
  it('allows ordinary business routes and protects admin route handles', () => {
    expect(routeAllowsRole('member', [undefined, {}])).toBe(true)
    expect(routeAllowsRole('admin', [{ roles: ['admin'] }])).toBe(true)
    expect(routeAllowsRole('executive', [{ roles: ['admin'] }])).toBe(false)
    expect(routeAllowsRole('member', [{ roles: ['admin'] }])).toBe(false)
  })

  it('fails closed for malformed role metadata', () => {
    expect(routeAllowsRole('member', [{ roles: ['owner'] }])).toBe(false)
  })
})

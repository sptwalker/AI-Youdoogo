import { describe, expect, it } from 'vitest'
import {
  InvalidConfigValue,
  configInitialValue,
  localDateInputValue,
  normalizeConfigValue,
} from './systemConfigModel'

describe('system config model', () => {
  it('accepts only explicit booleans instead of silently converting typos to false', () => {
    expect(normalizeConfigValue('bool', true)).toBe(true)
    expect(normalizeConfigValue('bool', ' false ')).toBe(false)
    expect(() => normalizeConfigValue('bool', 'treu')).toThrow(InvalidConfigValue)
  })

  it('rejects invalid and unsafe integers before they reach JSON serialization', () => {
    expect(normalizeConfigValue('int', '42')).toBe(42)
    expect(() => normalizeConfigValue('int', '4.2')).toThrow(InvalidConfigValue)
    expect(() => normalizeConfigValue('int', 'abc')).toThrow(InvalidConfigValue)
    expect(() => normalizeConfigValue('int', Number.MAX_SAFE_INTEGER + 1)).toThrow(InvalidConfigValue)
  })

  it('provides typed form values and uses the local calendar date', () => {
    expect(configInitialValue('bool', 'true')).toBe(true)
    expect(configInitialValue('int', '7')).toBe(7)
    expect(configInitialValue('text', null)).toBe('')
    expect(localDateInputValue(new Date(2026, 6, 24, 1, 30))).toBe('2026-07-24')
  })
})

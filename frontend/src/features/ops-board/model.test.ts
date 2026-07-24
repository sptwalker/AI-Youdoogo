import { describe, expect, it } from 'vitest'
import { valueForDate } from './model'

describe('ops board result model', () => {
  it('never displays analysis generated for a different selected date', () => {
    const result = { date: '2026-07-23', value: { content: 'day A' } }
    expect(valueForDate(result, '2026-07-23')).toEqual({ content: 'day A' })
    expect(valueForDate(result, '2026-07-24')).toBeNull()
  })
})

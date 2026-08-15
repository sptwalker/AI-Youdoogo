import { buildSuggestQuery } from './suggest'
import { describe, expect, it } from 'vitest'

describe('buildSuggestQuery', () => {
  it('combines title and description', () => {
    expect(buildSuggestQuery('季度复盘', '销售数据')).toBe('季度复盘 销售数据')
  })

  it('returns null when combined query is too short', () => {
    expect(buildSuggestQuery('', '')).toBeNull()
    expect(buildSuggestQuery(' ', null)).toBeNull()
    expect(buildSuggestQuery('a', null)).toBeNull()
  })

  it('trims and keeps a description-only query', () => {
    expect(buildSuggestQuery(undefined, '  写月报  ')).toBe('写月报')
  })
})

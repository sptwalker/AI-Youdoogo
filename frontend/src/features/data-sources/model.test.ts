import { describe, expect, it } from 'vitest'
import type { OpsEventGroup } from './api'
import {
  aliasesFromEdits,
  defaultEventDate,
  editsFromGroups,
  eventEditKey,
  secretStatusView,
} from './model'

const groups: OpsEventGroup[] = [{
  view: 'game_a',
  product: 'Game A',
  events: [
    { event_code: 'login', count: 12, display_name: '登录' },
    { event_code: 'pay', count: 3, display_name: '付费' },
  ],
}]

describe('data source feature model', () => {
  it('keeps the existing secret status labels and colors', () => {
    expect(secretStatusView('not_set')).toEqual({ color: 'default', text: '无密钥' })
    expect(secretStatusView('configured')).toEqual({ color: 'success', text: '已配置' })
    expect(secretStatusView('missing')).toEqual({ color: 'error', text: '缺失(.env未设)' })
  })

  it('defaults to yesterday without embedding date logic in the route', () => {
    expect(defaultEventDate(new Date('2026-07-23T12:00:00Z'))).toBe('2026-07-22')
  })

  it('round-trips event aliases through the local edit buffer', () => {
    const edits = editsFromGroups(groups)
    expect(edits).toEqual({
      [eventEditKey('game_a', 'login')]: '登录',
      [eventEditKey('game_a', 'pay')]: '付费',
    })
    expect(aliasesFromEdits(edits)).toEqual([
      { view: 'game_a', event_code: 'login', display_name: '登录' },
      { view: 'game_a', event_code: 'pay', display_name: '付费' },
    ])
  })
})

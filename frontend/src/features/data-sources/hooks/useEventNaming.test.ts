// @vitest-environment jsdom

import { message } from 'antd'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { dataSourcesApi, type OpsEventGroup } from '../api'
import { defaultEventDate, eventEditKey } from '../model'
import { useEventNaming } from './useEventNaming'

Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', {
  configurable: true,
  value: true,
})

const groups: OpsEventGroup[] = [{
  view: 'game_a',
  product: 'Game A',
  events: [{ event_code: 'login', count: 2, display_name: '登录' }],
}]

async function flushEffects() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useEventNaming', () => {
  it('loads yesterday once, waits for an explicit date query, and saves the edit buffer', async () => {
    const expectedInitialDate = defaultEventDate()
    const listEvents = vi.spyOn(dataSourcesApi, 'listOpsEvents').mockResolvedValue(groups)
    const saveAliases = vi.spyOn(dataSourcesApi, 'saveEventAliases').mockResolvedValue({ saved: 1 })
    vi.spyOn(message, 'success').mockImplementation(() => undefined as never)
    const root = createRoot(document.createElement('div'))
    let current: ReturnType<typeof useEventNaming> | undefined

    function Probe() {
      current = useEventNaming()
      return null
    }

    await act(async () => root.render(createElement(Probe)))
    await flushEffects()
    expect(listEvents).toHaveBeenCalledWith(expectedInitialDate)
    expect(current?.edits).toEqual({ [eventEditKey('game_a', 'login')]: '登录' })

    await act(async () => current?.setStatDate('2026-07-01'))
    expect(listEvents).toHaveBeenCalledTimes(1)
    expect(current?.loadedDate).toBe(expectedInitialDate)
    await act(async () => { await current?.load() })
    expect(listEvents).toHaveBeenLastCalledWith('2026-07-01')
    expect(current?.loadedDate).toBe('2026-07-01')

    await act(async () => current?.updateEdit(eventEditKey('game_a', 'login'), '用户登录'))
    await act(async () => { await current?.save() })
    expect(saveAliases).toHaveBeenCalledWith([
      { view: 'game_a', event_code: 'login', display_name: '用户登录' },
    ])
    expect(listEvents).toHaveBeenLastCalledWith('2026-07-01')
    await act(async () => root.unmount())
  })

  it('ignores a slower stale date response', async () => {
    let resolveFirst!: (value: OpsEventGroup[]) => void
    const first = new Promise<OpsEventGroup[]>((resolve) => { resolveFirst = resolve })
    const listEvents = vi.spyOn(dataSourcesApi, 'listOpsEvents')
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce(groups)
    const root = createRoot(document.createElement('div'))
    let current: ReturnType<typeof useEventNaming> | undefined

    function Probe() {
      current = useEventNaming()
      return null
    }

    await act(async () => root.render(createElement(Probe)))
    await act(async () => current?.setStatDate('2026-07-01'))
    await act(async () => { await current?.load() })
    expect(current?.loadedDate).toBe('2026-07-01')

    resolveFirst([{ ...groups[0], product: 'stale' }])
    await flushEffects()
    expect(listEvents).toHaveBeenCalledTimes(2)
    expect(current?.loadedDate).toBe('2026-07-01')
    expect(current?.groups[0]?.product).toBe('Game A')
    await act(async () => root.unmount())
  })
})

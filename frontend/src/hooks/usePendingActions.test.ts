// @vitest-environment jsdom

import { act, createElement, StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it, vi } from 'vitest'
import { usePendingActions } from './usePendingActions'

Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', {
  configurable: true,
  value: true,
})

describe('usePendingActions', () => {
  it('deduplicates an action key and clears it after completion in StrictMode', async () => {
    let resolve!: () => void
    const action = vi.fn(() => new Promise<void>((done) => { resolve = done }))
    const root = createRoot(document.createElement('div'))
    let current: ReturnType<typeof usePendingActions> | undefined

    function Probe() {
      current = usePendingActions()
      return null
    }

    await act(async () => root.render(createElement(StrictMode, null, createElement(Probe))))
    await act(async () => {
      void current?.run('same', action)
      void current?.run('same', action)
      await Promise.resolve()
    })

    expect(action).toHaveBeenCalledOnce()
    expect(current?.isPending('same')).toBe(true)
    resolve()
    await act(async () => { await Promise.resolve() })
    expect(current?.isPending('same')).toBe(false)
    await act(async () => root.unmount())
  })
})

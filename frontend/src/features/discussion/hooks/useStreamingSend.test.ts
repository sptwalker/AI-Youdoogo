// @vitest-environment jsdom

import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it, vi } from 'vitest'
import type { StreamingSend } from './useStreamingSend'
import { useStreamingSend } from './useStreamingSend'

Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', {
  configurable: true,
  value: true,
})

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

async function renderHook(onError: () => void) {
  const root = createRoot(document.createElement('div'))
  let current: StreamingSend | undefined
  function Probe() {
    current = useStreamingSend(onError)
    return null
  }
  await act(async () => root.render(createElement(Probe)))
  return {
    get current() {
      if (!current) throw new Error('hook did not render')
      return current
    },
    unmount: async () => { await act(async () => root.unmount()) },
  }
}

describe('useStreamingSend', () => {
  it('tracks sending, single-flights the ref, and aborts on unmount', async () => {
    const gate = deferred<void>()
    const rendered = await renderHook(vi.fn())
    let seenSignal: AbortSignal | undefined

    await act(async () => {
      void rendered.current.submit(async (signal) => { seenSignal = signal; await gate.promise })
      await Promise.resolve()
    })
    expect(rendered.current.sending).toBe(true)
    expect(rendered.current.sendingRef.current).toBe(true)

    gate.resolve()
    await act(async () => { await Promise.resolve() })
    expect(rendered.current.sending).toBe(false)
    expect(rendered.current.sendingRef.current).toBe(false)
    expect(seenSignal?.aborted).toBe(false)

    await rendered.unmount()
  })

  it('routes a failed send through the error callback and still clears sending', async () => {
    const onError = vi.fn()
    const rendered = await renderHook(onError)

    await act(async () => {
      await rendered.current.submit(async () => { throw new Error('stream failed') })
    })

    expect(onError).toHaveBeenCalledOnce()
    expect(rendered.current.sending).toBe(false)
    expect(rendered.current.sendingRef.current).toBe(false)
    await rendered.unmount()
  })

  it('aborts the in-flight request when the component unmounts', async () => {
    const gate = deferred<void>()
    const rendered = await renderHook(vi.fn())
    let seenSignal: AbortSignal | undefined

    await act(async () => {
      void rendered.current.submit(async (signal) => { seenSignal = signal; await gate.promise })
      await Promise.resolve()
    })
    await rendered.unmount()
    expect(seenSignal?.aborted).toBe(true)
    gate.resolve()
  })
})

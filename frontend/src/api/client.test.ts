// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest'
import { sseSubscribe, type SseConnectionState } from './client'

function sseResponse(frames: string): Response {
  const encoded = new TextEncoder().encode(frames)
  return new Response(new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoded)
      controller.close()
    },
  }), { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('sseSubscribe', () => {
  it('parses messages and reports connection state', async () => {
    const fetchMock = vi.fn().mockResolvedValue(sseResponse(
      'event: ready\ndata: {"channels":1}\n\n'
      + 'event: message\ndata: {"text":"hello"}\n\n',
    ))
    vi.stubGlobal('fetch', fetchMock)
    const events: Array<[string, Record<string, unknown>]> = []
    const states: SseConnectionState[] = []

    const subscription = sseSubscribe(
      '/channels/realtime/stream',
      (event, data) => events.push([event, data]),
      { onStateChange: (state) => states.push(state), initialRetryDelayMs: 10000 },
    )

    await vi.waitFor(() => expect(events).toEqual([['message', { text: 'hello' }]]))
    expect(states).toContain('connected')
    subscription()
  })

  it('automatically reconnects after a remote close', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse('event: ready\ndata: {"channels":1}\n\n'),
    )
    vi.stubGlobal('fetch', fetchMock)

    const subscription = sseSubscribe(
      '/channels/realtime/stream',
      () => {},
      { initialRetryDelayMs: 250, maxRetryDelayMs: 250 },
    )

    await vi.waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2), {
      timeout: 1500,
    })
    subscription()
  })

  it('restart aborts the current attempt and reconnects immediately', async () => {
    const fetchMock = vi.fn()
      .mockImplementationOnce((_url: string, init: RequestInit) => new Promise<Response>(
        (_resolve, reject) => {
          init.signal?.addEventListener('abort', () => {
            reject(new DOMException('aborted', 'AbortError'))
          })
        },
      ))
      .mockResolvedValue(sseResponse('event: ready\ndata: {"channels":1}\n\n'))
    vi.stubGlobal('fetch', fetchMock)

    const subscription = sseSubscribe('/channels/realtime/stream', () => {}, {
      initialRetryDelayMs: 30000,
    })
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    subscription.restart()
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2), { timeout: 500 })
    subscription()
  })
})

// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest'
import { sseRequest, sseSubscribe, type SseConnectionState } from './client'

function sseResponse(...chunks: string[]): Response {
  return new Response(new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk))
      controller.close()
    },
  }), { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

function openSseResponse(...chunks: string[]): Response {
  return new Response(new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk))
    },
  }), { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('sseRequest', () => {
  it('parses CRLF frames split across chunks and preserves event order', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse(
      'event: message\r',
      '\ndata: {"index":1}\r\n\r',
      '\nevent: delta\r\ndata: {"index":2}\r\n\r\n',
    )))
    const events: Array<[string, Record<string, unknown>]> = []

    await sseRequest('/desktop/chat', { message: 'hello' }, (event, data) => {
      events.push([event, data])
    })

    expect(events).toEqual([
      ['message', { index: 1 }],
      ['delta', { index: 2 }],
    ])
  })

  it('rejects malformed JSON frames', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse(
      'event: delta\ndata: not-json\n\n',
    )))

    await expect(sseRequest('/desktop/chat', {}, () => {})).rejects.toBeInstanceOf(SyntaxError)
  })
})

describe('sseSubscribe', () => {
  it('parses messages and reports connection state', async () => {
    const fetchMock = vi.fn().mockResolvedValue(sseResponse(
      'event: ready\r\ndata: {"channels":1}\r\n\r',
      '\nevent: message\r',
      '\ndata: {"text":"hello"}\r\n\r\n',
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

  it('keeps the connection after malformed data or a callback error and reports both', async () => {
    const callbackError = new Error('consumer failed')
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const fetchMock = vi.fn().mockResolvedValue(openSseResponse(
      'event: message\ndata: not-json\n\n',
      'event: message\ndata: {"id":"fails"}\n\n',
      'event: message\ndata: {"id":"after"}\n\n',
    ))
    vi.stubGlobal('fetch', fetchMock)
    const events: Array<[string, Record<string, unknown>]> = []

    const subscription = sseSubscribe('/channels/realtime/stream', (event, data) => {
      events.push([event, data])
      if (data.id === 'fails') throw callbackError
    })

    await vi.waitFor(() => expect(events).toEqual([
      ['message', { id: 'fails' }],
      ['message', { id: 'after' }],
    ]))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(warn).toHaveBeenCalledWith(
      'SSE 订阅忽略了无法解析的 message 数据帧',
      expect.any(SyntaxError),
    )
    expect(warn).toHaveBeenCalledWith('SSE 订阅的 message 回调执行失败', callbackError)
    subscription()
  })
})

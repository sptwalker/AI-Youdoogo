// @vitest-environment jsdom

import { message } from 'antd'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  loginRedirectPath,
  parseStreamEvent,
  request,
  sseRequest,
  sseSubscribe,
  TOKEN_KEY,
  type SseConnectionState,
} from './client'

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

describe('stream event parsing', () => {
  it('normalizes typed stream payloads without changing wire event names', () => {
    expect(parseStreamEvent<{ id: string }>('message_start', {
      speaker_agent_id: 'agent-1',
      speaker_name: 'Planner',
    })).toEqual({
      type: 'message_start',
      payload: { speaker_agent_id: 'agent-1', speaker_name: 'Planner' },
    })

    expect(parseStreamEvent<{ id: string }>('delta', { text: 123 })).toEqual({
      type: 'delta',
      payload: { text: '123' },
    })

    expect(parseStreamEvent<{ id: string }>('message_end', { id: 'm-1' })).toEqual({
      type: 'message_end',
      payload: { id: 'm-1' },
    })

    expect(parseStreamEvent<{ id: string }, { step: number }>('orchestration', { step: 2 })).toEqual({
      type: 'orchestration',
      payload: { step: 2 },
    })

    expect(parseStreamEvent('unknown', { x: 1 })).toBeNull()
  })
})

describe('authentication failures', () => {
  it('preserves the current application location when login is required', () => {
    expect(loginRedirectPath({ pathname: '/tasks', search: '?status=todo' })).toBe(
      '/login?return_to=%2Ftasks%3Fstatus%3Dtodo',
    )
    expect(loginRedirectPath({ pathname: '/login', search: '?return_to=%2Ftasks' })).toBeNull()
  })

  it('shows a password-login 401 instead of silently treating it as an expired session', async () => {
    window.history.replaceState({}, '', '/login')
    localStorage.setItem(TOKEN_KEY, 'stale-token')
    const errorMessage = vi.spyOn(message, 'error').mockImplementation(() => undefined as never)

    await expect(request({
      method: 'POST',
      url: '/auth/login',
      adapter: async (config) => Promise.reject({
        config,
        response: { status: 401, data: { msg: '用户名或密码错误' } },
      }),
    })).rejects.toBeInstanceOf(ApiError)

    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
    expect(errorMessage).toHaveBeenCalledWith('用户名或密码错误')
  })
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

    await expect(sseRequest('/desktop/chat', {}, () => {}, { silent: true })).rejects.toMatchObject({
      name: 'ApiError',
      message: '服务器返回了无法解析的流式数据',
    })
  })

  it('cancels an active stream through the caller signal', async () => {
    const fetchMock = vi.fn((_url: string, init: RequestInit) => new Promise<Response>(
      (_resolve, reject) => {
        init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
      },
    ))
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()
    const pending = sseRequest('/desktop/chat', {}, () => {}, {
      signal: controller.signal,
      silent: true,
    })

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledOnce())
    controller.abort()
    await expect(pending).rejects.toMatchObject({ name: 'ApiError', cancelled: true })
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

import axios, { type AxiosRequestConfig } from 'axios'
import { message } from 'antd'

/** HTTP/SSE transport: one owner for credentials, API errors and stream handling. */
export const TOKEN_KEY = 'youdoo_token'

interface BrowserLocation {
  pathname: string
  search: string
}

export function loginRedirectPath(location: BrowserLocation, expired = false): string | null {
  if (location.pathname === '/login') return null
  const params = new URLSearchParams({ return_to: `${location.pathname}${location.search}` })
  if (expired) params.set('expired', '1')
  return `/login?${params.toString()}`
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY) ?? sessionStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string, remember: boolean): void {
  const [keep, drop] = remember ? [localStorage, sessionStorage] : [sessionStorage, localStorage]
  keep.setItem(TOKEN_KEY, token)
  drop.removeItem(TOKEN_KEY)
}

export function clearSessionAndRedirectToLogin(expired = true): boolean {
  localStorage.removeItem(TOKEN_KEY)
  sessionStorage.removeItem(TOKEN_KEY)
  const redirectPath = loginRedirectPath(window.location, expired)
  if (!redirectPath) return false
  void import('../router')
    .then(({ router }) => router.navigate(redirectPath))
    .catch(() => { window.location.href = redirectPath })
  return true
}

export interface ApiErrorOptions {
  status?: number
  code?: number
  cancelled?: boolean
  cause?: unknown
}

export class ApiError extends Error {
  readonly status?: number
  readonly code?: number
  readonly cancelled: boolean
  readonly cause?: unknown

  constructor(messageText: string, options: ApiErrorOptions = {}) {
    super(messageText)
    this.name = 'ApiError'
    this.status = options.status
    this.code = options.code
    this.cancelled = options.cancelled ?? false
    this.cause = options.cause
  }
}

export interface ApiEnvelope<T> {
  code: number
  msg: string
  data: T
}

export interface RequestConfig<D = unknown> extends AxiosRequestConfig<D> {
  /** Let the calling screen render an intentional inline fallback instead of a global toast. */
  silent?: boolean
}

const http = axios.create({ baseURL: '/api/v1', timeout: 15000 })

http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (axios.isCancel(error)) {
      return Promise.reject(new ApiError('请求已取消', { cancelled: true, cause: error }))
    }
    const status = error.response?.status
    const responseData = error.response?.data as {
      msg?: string
      detail?: string
      code?: number
    } | undefined
    const errorMessage = responseData?.msg ?? responseData?.detail ?? '网络错误'
    const silent = Boolean((error.config as RequestConfig | undefined)?.silent)
    if (status === 401) {
      const redirected = clearSessionAndRedirectToLogin()
      // A credential failure on the login page is user feedback, not session expiry.
      if (!redirected && !silent) message.error(errorMessage)
    } else if (!silent) {
      message.error(errorMessage)
    }
    return Promise.reject(new ApiError(errorMessage, {
      status,
      code: responseData?.code,
      cause: error,
    }))
  },
)

/** 请求并解包统一响应格式，code!=0 抛错。 */
export async function request<T>(config: RequestConfig): Promise<T> {
  const response = await http.request<ApiEnvelope<T>>(config)
  if (response.data.code !== 0) {
    if (!config.silent) message.error(response.data.msg)
    throw new ApiError(response.data.msg, { code: response.data.code })
  }
  return response.data.data
}

export type SseHandler = (event: string, data: Record<string, unknown>) => void
export type SseConnectionState = 'connecting' | 'connected' | 'disconnected'

export interface SseSubscribeOptions {
  onStateChange?: (state: SseConnectionState) => void
  initialRetryDelayMs?: number
  maxRetryDelayMs?: number
}

export interface SseRequestOptions {
  signal?: AbortSignal
  idleTimeoutMs?: number
  silent?: boolean
}

export interface SseSubscription {
  (): void
  restart: () => void
}

export interface StreamTurnStartPayload {
  speaker_agent_id: string | null
  speaker_name: string
}

export interface StreamDeltaPayload {
  text: string
}

export type ParsedStreamEvent<TPersistedMessage, TOrchestration = never> =
  | { type: 'message_start'; payload: StreamTurnStartPayload }
  | { type: 'delta'; payload: StreamDeltaPayload }
  | { type: 'message_end'; payload: TPersistedMessage }
  | { type: 'orchestration'; payload: TOrchestration }
  | { type: 'done'; payload: Record<string, unknown> }

export function parseStreamEvent<TPersistedMessage, TOrchestration = never>(
  event: string,
  data: Record<string, unknown>,
): ParsedStreamEvent<TPersistedMessage, TOrchestration> | null {
  if (event === 'message_start') return {
    type: 'message_start',
    payload: {
      speaker_agent_id: typeof data.speaker_agent_id === 'string' ? data.speaker_agent_id : null,
      speaker_name: String(data.speaker_name ?? ''),
    },
  }
  if (event === 'delta') return { type: 'delta', payload: { text: String(data.text ?? '') } }
  if (event === 'message_end') return { type: 'message_end', payload: data as TPersistedMessage }
  if (event === 'orchestration') return { type: 'orchestration', payload: data as TOrchestration }
  if (event === 'done') return { type: 'done', payload: data }
  return null
}

interface SseFrame {
  event: string
  data: string
}

const SSE_FRAME_SEPARATOR = /\r\n\r\n|\n\n|\r\r/

function parseSseFrame(rawFrame: string): SseFrame | null {
  let event = 'message'
  let data = ''
  for (const line of rawFrame.split(/\r\n|\n|\r/)) {
    const separatorIndex = line.indexOf(':')
    const field = separatorIndex >= 0 ? line.slice(0, separatorIndex) : line
    const rawValue = separatorIndex >= 0 ? line.slice(separatorIndex + 1) : ''
    const value = rawValue.startsWith(' ') ? rawValue.slice(1) : rawValue
    if (field === 'event') event = value
    else if (field === 'data') data = value
  }
  return data ? { event, data } : null
}

async function consumeSseStream(
  body: ReadableStream<Uint8Array>,
  onFrame: (frame: SseFrame) => void,
  onActivity?: () => void,
): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const consumeCompleteFrames = () => {
    for (;;) {
      const separator = SSE_FRAME_SEPARATOR.exec(buffer)
      if (!separator || separator.index === undefined) return
      const rawFrame = buffer.slice(0, separator.index)
      buffer = buffer.slice(separator.index + separator[0].length)
      const frame = parseSseFrame(rawFrame)
      if (frame) onFrame(frame)
    }
  }
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      onActivity?.()
      buffer += decoder.decode(value, { stream: true })
      consumeCompleteFrames()
    }
    buffer += decoder.decode()
    consumeCompleteFrames()
  } catch (error) {
    try {
      await reader.cancel(error)
    } catch {
      // The transport may already be closed by AbortController.
    }
    throw error
  } finally {
    reader.releaseLock()
  }
}

/** POST one SSE endpoint. fetch carries the token because EventSource cannot. */
export async function sseRequest(
  url: string,
  body: unknown,
  onEvent: SseHandler,
  options: SseRequestOptions = {},
): Promise<void> {
  const controller = new AbortController()
  const idleTimeoutMs = Math.max(0, options.idleTimeoutMs ?? 180000)
  let timeoutId: number | undefined
  let timedOut = false
  const clearIdleTimeout = () => {
    if (timeoutId !== undefined) window.clearTimeout(timeoutId)
    timeoutId = undefined
  }
  const armIdleTimeout = () => {
    clearIdleTimeout()
    if (idleTimeoutMs === 0) return
    timeoutId = window.setTimeout(() => {
      timedOut = true
      controller.abort(new DOMException('SSE idle timeout', 'TimeoutError'))
    }, idleTimeoutMs)
  }
  const abortFromCaller = () => controller.abort(options.signal?.reason)
  if (options.signal?.aborted) abortFromCaller()
  else options.signal?.addEventListener('abort', abortFromCaller, { once: true })
  armIdleTimeout()
  try {
    const token = getToken()
    const response = await fetch(`/api/v1${url}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
    if (response.status === 401) {
      clearSessionAndRedirectToLogin()
      throw new ApiError('未登录或登录已过期', { status: 401 })
    }
    if (!response.ok || !response.body) {
      let errorMessage = '网络错误'
      try {
        const responseData = await response.json() as { msg?: string; detail?: string }
        errorMessage = responseData.msg ?? responseData.detail ?? errorMessage
      } catch { /* non-JSON response */ }
      if (!options.silent) message.error(errorMessage)
      throw new ApiError(errorMessage, { status: response.status })
    }
    await consumeSseStream(response.body, ({ event, data }) => {
      let parsed: Record<string, unknown>
      try {
        parsed = JSON.parse(data) as Record<string, unknown>
      } catch (error) {
        const errorMessage = '服务器返回了无法解析的流式数据'
        if (!options.silent) message.error(errorMessage)
        throw new ApiError(errorMessage, { cause: error })
      }
      if (event === 'error') {
        const errorMessage = String(parsed.msg ?? '服务器错误')
        if (!options.silent) message.error(errorMessage)
        throw new ApiError(errorMessage)
      }
      onEvent(event, parsed)
    }, armIdleTimeout)
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (timedOut) {
      const errorMessage = '流式请求长时间没有响应，已自动停止'
      if (!options.silent) message.error(errorMessage)
      throw new ApiError(errorMessage, { cancelled: true, cause: error })
    }
    if (controller.signal.aborted) throw new ApiError('请求已取消', { cancelled: true, cause: error })
    throw error
  } finally {
    clearIdleTimeout()
    options.signal?.removeEventListener('abort', abortFromCaller)
  }
}

/** GET long-lived SSE subscription with reconnect/backoff. */
export function sseSubscribe(
  url: string,
  onEvent: SseHandler,
  options: SseSubscribeOptions = {},
): SseSubscription {
  const initialRetryDelayMs = Math.max(250, options.initialRetryDelayMs ?? 1000)
  const maxRetryDelayMs = Math.max(initialRetryDelayMs, options.maxRetryDelayMs ?? 30000)
  let stopped = false
  let restartRequested = false
  let activeController: AbortController | null = null
  let wakeRetry: (() => void) | null = null
  let lastState: SseConnectionState | null = null
  const reportState = (state: SseConnectionState) => {
    if (lastState === state) return
    lastState = state
    options.onStateChange?.(state)
  }
  const waitForRetry = (delayMs: number) => new Promise<void>((resolve) => {
    let settled = false
    const finish = () => {
      if (settled) return
      settled = true
      window.clearTimeout(timer)
      if (wakeRetry === finish) wakeRetry = null
      resolve()
    }
    const timer = window.setTimeout(finish, delayMs)
    wakeRetry = finish
  })
  const connectLoop = async () => {
    let retryDelayMs = initialRetryDelayMs
    while (!stopped) {
      restartRequested = false
      const controller = new AbortController()
      activeController = controller
      let connected = false
      reportState('connecting')
      try {
        const token = getToken()
        const response = await fetch(`/api/v1${url}`, {
          method: 'GET', headers: token ? { Authorization: `Bearer ${token}` } : {}, signal: controller.signal,
        })
        if (response.status === 401) {
          clearSessionAndRedirectToLogin()
          stopped = true
          reportState('disconnected')
          return
        }
        if (!response.ok || !response.body) throw new ApiError(`实时连接失败（${response.status}）`)
        await consumeSseStream(response.body, ({ event, data }) => {
          if (!connected && event !== 'done') {
            connected = true
            retryDelayMs = initialRetryDelayMs
            reportState('connected')
          }
          if (event === 'ping' || event === 'ready' || event === 'done') return
          let parsed: Record<string, unknown>
          try {
            parsed = JSON.parse(data) as Record<string, unknown>
          } catch (error) {
            console.warn(`SSE 订阅忽略了无法解析的 ${event} 数据帧`, error)
            return
          }
          try {
            onEvent(event, parsed)
          } catch (error) {
            console.warn(`SSE 订阅的 ${event} 回调执行失败`, error)
          }
        })
      } catch (error) {
        if (stopped) return
        if (error instanceof DOMException && error.name === 'AbortError' && restartRequested) {
          // An explicit restart does not count toward backoff.
        }
      } finally {
        if (activeController === controller) activeController = null
      }
      if (stopped) return
      reportState('disconnected')
      if (restartRequested) {
        retryDelayMs = initialRetryDelayMs
        continue
      }
      await waitForRetry(retryDelayMs)
      if (restartRequested) {
        retryDelayMs = initialRetryDelayMs
        continue
      }
      retryDelayMs = Math.min(retryDelayMs * 2, maxRetryDelayMs)
    }
  }
  void connectLoop()
  const cancel = (() => {
    if (stopped) return
    stopped = true
    activeController?.abort()
    wakeRetry?.()
  }) as SseSubscription
  cancel.restart = () => {
    if (stopped) return
    restartRequested = true
    activeController?.abort()
    wakeRetry?.()
  }
  return cancel
}

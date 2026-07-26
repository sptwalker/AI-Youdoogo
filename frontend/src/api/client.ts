/** Axios 实例：统一 token 注入、{code,msg,data} 解包、401 跳登录。 */
import axios, { type AxiosRequestConfig } from 'axios'
import { message } from 'antd'

export const TOKEN_KEY = 'youdoo_token'

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

export interface ApiErrorOptions {
  status?: number
  code?: number
  cancelled?: boolean
  cause?: unknown
}

/** 可由页面按状态码、业务码或取消状态做局部恢复的统一 API 错误。 */
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

interface BrowserLocation {
  pathname: string
  search: string
}

/** Build one consistent login hand-off for route guards and every API transport. */
export function loginRedirectPath(location: BrowserLocation): string | null {
  if (location.pathname === '/login') return null
  const returnTo = `${location.pathname}${location.search}`
  return `/login?${new URLSearchParams({ return_to: returnTo }).toString()}`
}

export function clearSessionAndRedirectToLogin(): boolean {
  localStorage.removeItem(TOKEN_KEY)
  const redirectPath = loginRedirectPath(window.location)
  if (!redirectPath) return false
  window.location.href = redirectPath
  return true
}

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (resp) => resp,
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
    const msg = responseData?.msg ?? responseData?.detail ?? '网络错误'
    const silent = Boolean((error.config as RequestConfig | undefined)?.silent)
    if (status === 401) {
      const redirected = clearSessionAndRedirectToLogin()
      // A credential failure on the login page is user feedback, not session expiry.
      if (!redirected && !silent) message.error(msg)
    } else if (!silent) {
      message.error(msg)
    }
    return Promise.reject(new ApiError(msg, {
      status,
      code: responseData?.code,
      cause: error,
    }))
  },
)

/** 请求并解包统一响应格式，code!=0 抛错。 */
export async function request<T>(config: RequestConfig): Promise<T> {
  const resp = await http.request<ApiEnvelope<T>>(config)
  if (resp.data.code !== 0) {
    if (!config.silent) message.error(resp.data.msg)
    throw new ApiError(resp.data.msg, { code: resp.data.code })
  }
  return resp.data.data
}

// ── SSE（AI 对话逐字流式）────────────────────────────────
export type SseHandler = (event: string, data: Record<string, unknown>) => void

export interface StreamTurnStartPayload {
  speaker_agent_id: string | null
  speaker_name: string
}

export interface StreamDeltaPayload {
  text: string
}

export type ParsedStreamEvent<
  TPersistedMessage,
  TOrchestration = never,
> =
  | { type: 'message_start'; payload: StreamTurnStartPayload }
  | { type: 'delta'; payload: StreamDeltaPayload }
  | { type: 'message_end'; payload: TPersistedMessage }
  | { type: 'orchestration'; payload: TOrchestration }
  | { type: 'done'; payload: Record<string, unknown> }

export function parseStreamEvent<
  TPersistedMessage,
  TOrchestration = never,
>(
  event: string,
  data: Record<string, unknown>,
): ParsedStreamEvent<TPersistedMessage, TOrchestration> | null {
  if (event === 'message_start') {
    return {
      type: 'message_start',
      payload: {
        speaker_agent_id: typeof data.speaker_agent_id === 'string' ? data.speaker_agent_id : null,
        speaker_name: String(data.speaker_name ?? ''),
      },
    }
  }
  if (event === 'delta') {
    return { type: 'delta', payload: { text: String(data.text ?? '') } }
  }
  if (event === 'message_end') {
    return { type: 'message_end', payload: data as TPersistedMessage }
  }
  if (event === 'orchestration') {
    return { type: 'orchestration', payload: data as TOrchestration }
  }
  if (event === 'done') {
    return { type: 'done', payload: data }
  }
  return null
}

export type SseConnectionState = 'connecting' | 'connected' | 'disconnected'

export interface SseSubscribeOptions {
  onStateChange?: (state: SseConnectionState) => void
  initialRetryDelayMs?: number
  maxRetryDelayMs?: number
}

export interface SseRequestOptions {
  signal?: AbortSignal
  /** 最长无数据帧时间；设为 0 可关闭。 */
  idleTimeoutMs?: number
  silent?: boolean
}

/** 兼容原有“取消函数”用法，同时允许成员集合变化后立即重建订阅。 */
export interface SseSubscription {
  (): void
  restart: () => void
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

function reportMalformedSubscriptionFrame(event: string, error: unknown): void {
  console.warn(`SSE 订阅忽略了无法解析的 ${event} 数据帧`, error)
}

function reportSubscriptionCallbackError(event: string, error: unknown): void {
  console.warn(`SSE 订阅的 ${event} 回调执行失败`, error)
}

/** POST 一个 SSE 端点并逐事件回调（fetch 手动带 token——EventSource 不支持自定义头）。
 *  协议：message_start / delta / message_end / done / error；error 事件提示后抛出。 */
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

  const token = localStorage.getItem(TOKEN_KEY)
  armIdleTimeout()
  try {
    const resp = await fetch(`/api/v1${url}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
    if (resp.status === 401) {
      clearSessionAndRedirectToLogin()
      throw new ApiError('未登录或登录已过期', { status: 401 })
    }
    if (!resp.ok || !resp.body) {
      let msg = '网络错误'
      try {
        const responseData = await resp.json() as { msg?: string; detail?: string }
        msg = responseData.msg ?? responseData.detail ?? msg
      } catch { /* 非 JSON 响应体 */ }
      if (!options.silent) message.error(msg)
      throw new ApiError(msg, { status: resp.status })
    }
    await consumeSseStream(resp.body, ({ event, data }) => {
      let parsed: Record<string, unknown>
      try {
        parsed = JSON.parse(data) as Record<string, unknown>
      } catch (error) {
        const msg = '服务器返回了无法解析的流式数据'
        if (!options.silent) message.error(msg)
        throw new ApiError(msg, { cause: error })
      }
      if (event === 'error') {
        const msg = String(parsed.msg ?? '服务器错误')
        if (!options.silent) message.error(msg)
        throw new ApiError(msg)
      }
      onEvent(event, parsed)
    }, armIdleTimeout)
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (timedOut) {
      const msg = '流式请求长时间没有响应，已自动停止'
      if (!options.silent) message.error(msg)
      throw new ApiError(msg, { cancelled: true, cause: error })
    }
    if (controller.signal.aborted) {
      throw new ApiError('请求已取消', { cancelled: true, cause: error })
    }
    throw error
  } finally {
    clearIdleTimeout()
    options.signal?.removeEventListener('abort', abortFromCaller)
  }
}

/** GET 一个长连 SSE 订阅端点（实时消息推送，I3）。
 *  非主动断开后指数退避重连；返回值既可直接取消，也可在订阅集合变化后 restart。
 *  与 sseRequest 不同：GET、长生命周期、可 abort、忽略 ping/ready 心跳。 */
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
      const ctrl = new AbortController()
      activeController = ctrl
      let connected = false
      reportState('connecting')
      try {
        // 每次重连重新读取 token，避免长页面会话刷新后仍使用旧凭证。
        const token = localStorage.getItem(TOKEN_KEY)
        const resp = await fetch(`/api/v1${url}`, {
          method: 'GET',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          signal: ctrl.signal,
        })
        if (resp.status === 401) {
          clearSessionAndRedirectToLogin()
          stopped = true
          reportState('disconnected')
          return
        }
        if (!resp.ok || !resp.body) throw new ApiError(`实时连接失败（${resp.status}）`)

        await consumeSseStream(resp.body, ({ event, data }) => {
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
            reportMalformedSubscriptionFrame(event, error)
            return
          }
          try {
            onEvent(event, parsed)
          } catch (error) {
            reportSubscriptionCallbackError(event, error)
          }
        })
      } catch (error) {
        if (stopped) return
        if (error instanceof DOMException && error.name === 'AbortError' && restartRequested) {
          // 成员集合变化触发的主动重建，不计入失败退避。
        }
      } finally {
        if (activeController === ctrl) activeController = null
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

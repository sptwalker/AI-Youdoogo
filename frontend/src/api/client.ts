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

/** 已由拦截器/request 向用户提示过的 API 错误：全局据此抑制 unhandledrejection 噪音。 */
export class ApiError extends Error {}

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const status = error.response?.status
    const msg: string = error.response?.data?.msg ?? '网络错误'
    const silent = Boolean((error.config as RequestConfig | undefined)?.silent)
    if (status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      if (window.location.pathname !== '/login') window.location.href = '/login'
    } else if (!silent) {
      message.error(msg)
    }
    return Promise.reject(new ApiError(msg))
  },
)

/** 请求并解包统一响应格式，code!=0 抛错。 */
export async function request<T>(config: RequestConfig): Promise<T> {
  const resp = await http.request<ApiEnvelope<T>>(config)
  if (resp.data.code !== 0) {
    if (!config.silent) message.error(resp.data.msg)
    throw new ApiError(resp.data.msg)
  }
  return resp.data.data
}

// ── SSE（AI 对话逐字流式）────────────────────────────────
export type SseHandler = (event: string, data: Record<string, unknown>) => void

export type SseConnectionState = 'connecting' | 'connected' | 'disconnected'

export interface SseSubscribeOptions {
  onStateChange?: (state: SseConnectionState) => void
  initialRetryDelayMs?: number
  maxRetryDelayMs?: number
}

/** 兼容原有“取消函数”用法，同时允许成员集合变化后立即重建订阅。 */
export interface SseSubscription {
  (): void
  restart: () => void
}

/** POST 一个 SSE 端点并逐事件回调（fetch 手动带 token——EventSource 不支持自定义头）。
 *  协议：message_start / delta / message_end / done / error；error 事件提示后抛出。 */
export async function sseRequest(url: string, body: unknown, onEvent: SseHandler): Promise<void> {
  const token = localStorage.getItem(TOKEN_KEY)
  const resp = await fetch(`/api/v1${url}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  })
  if (resp.status === 401) {
    // 复刻 axios 拦截器的 401 处理
    localStorage.removeItem(TOKEN_KEY)
    if (window.location.pathname !== '/login') window.location.href = '/login'
    throw new ApiError('未登录或登录已过期')
  }
  if (!resp.ok || !resp.body) {
    let msg = '网络错误'
    try {
      msg = (await resp.json())?.msg ?? msg
    } catch { /* 非 JSON 响应体 */ }
    message.error(msg)
    throw new ApiError(msg)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      let event = 'message'
      let data = ''
      for (const line of frame.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7)
        else if (line.startsWith('data: ')) data = line.slice(6)
      }
      if (!data) continue
      const parsed = JSON.parse(data) as Record<string, unknown>
      if (event === 'error') {
        const msg = String(parsed.msg ?? '服务器错误')
        message.error(msg)
        throw new ApiError(msg)
      }
      onEvent(event, parsed)
    }
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
          localStorage.removeItem(TOKEN_KEY)
          if (window.location.pathname !== '/login') window.location.href = '/login'
          stopped = true
          reportState('disconnected')
          return
        }
        if (!resp.ok || !resp.body) throw new ApiError(`实时连接失败（${resp.status}）`)

        const reader = resp.body.getReader()
        const decoder = new TextDecoder()
        let buf = ''
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true }).replaceAll('\r\n', '\n')
          let idx: number
          while ((idx = buf.indexOf('\n\n')) >= 0) {
            const frame = buf.slice(0, idx)
            buf = buf.slice(idx + 2)
            let event = 'message'
            let data = ''
            for (const line of frame.split('\n')) {
              if (line.startsWith('event: ')) event = line.slice(7)
              else if (line.startsWith('data: ')) data = line.slice(6)
            }
            if (!data) continue
            if (!connected && event !== 'done') {
              connected = true
              retryDelayMs = initialRetryDelayMs
              reportState('connected')
            }
            if (event === 'ping' || event === 'ready' || event === 'done') continue
            try {
              onEvent(event, JSON.parse(data) as Record<string, unknown>)
            } catch { /* 跳过无法解析的帧或业务回调异常，保持订阅 */ }
          }
        }
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

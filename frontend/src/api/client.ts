/** Axios 实例：统一 token 注入、{code,msg,data} 解包、401 跳登录。 */
import axios from 'axios'
import { message } from 'antd'

export const TOKEN_KEY = 'youdoo_token'

export interface ApiEnvelope<T> {
  code: number
  msg: string
  data: T
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
    if (status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      if (window.location.pathname !== '/login') window.location.href = '/login'
    } else {
      message.error(msg)
    }
    return Promise.reject(new ApiError(msg))
  },
)

/** 请求并解包统一响应格式，code!=0 抛错。 */
export async function request<T>(config: Parameters<typeof http.request>[0]): Promise<T> {
  const resp = await http.request<ApiEnvelope<T>>(config)
  if (resp.data.code !== 0) {
    message.error(resp.data.msg)
    throw new ApiError(resp.data.msg)
  }
  return resp.data.data
}

/** 鉴权与用户管理 API（对应后端 app/api/v1/auth.py 与 users.py）。 */
import { request } from './client'

export interface TokenData {
  access_token: string
  token_type: string
  expires_in: number
}

export interface UserInfo {
  id: string
  username: string
  real_name: string
  role_code: 'admin' | 'executive' | 'member'
  department_id: string | null
  is_active: boolean
  create_time: string
}

export const ROLE_LABELS: Record<UserInfo['role_code'], string> = {
  admin: '超级管理员',
  executive: '高管',
  member: '成员',
}

export function login(username: string, password: string): Promise<TokenData> {
  return request({ method: 'POST', url: '/auth/login', data: { username, password } })
}

/** 获取飞书扫码登录授权 URL（I2）。 */
export function feishuLoginUrl(redirectUri: string, state = ''): Promise<{ url: string }> {
  return request({ method: 'GET', url: '/auth/feishu/url', params: { redirect_uri: redirectUri, state } })
}

/** 飞书回调 code 换登录令牌（I2）。 */
export function feishuCallback(code: string): Promise<TokenData> {
  return request({ method: 'POST', url: '/auth/feishu/callback', data: { code } })
}

export function fetchMe(): Promise<UserInfo> {
  return request({ method: 'GET', url: '/auth/me' })
}

export function listUsers(): Promise<UserInfo[]> {
  return request({ method: 'GET', url: '/users' })
}

export interface Colleague {
  id: string
  real_name: string
  en_name: string
  username: string
  title: string
  department_id: string | null
}

/** 同事花名册（任意登录用户可读，群聊选人用）。 */
export function roster(): Promise<Colleague[]> {
  return request({ method: 'GET', url: '/users/roster' })
}

export interface UserCreatePayload {
  username: string
  password: string
  real_name?: string
  role_code?: string
}

export function createUser(payload: UserCreatePayload): Promise<UserInfo> {
  return request({ method: 'POST', url: '/users', data: payload })
}

export function updateUser(
  id: string,
  payload: Partial<{ is_active: boolean; role_code: string; real_name: string; password: string }>,
): Promise<UserInfo> {
  return request({ method: 'PATCH', url: `/users/${id}`, data: payload })
}

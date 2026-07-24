import type { UserCreatePayload, UserInfo } from '../api/auth'

export interface UserCreateFormValues {
  username: string
  password: string
  real_name?: string
  role_code: UserInfo['role_code']
  feishu_open_id?: string
}

export function normalizeUserCreateValues(values: UserCreateFormValues): UserCreatePayload {
  return {
    ...values,
    feishu_open_id: values.feishu_open_id?.trim() || undefined,
  }
}

export function validateOptionalFeishuOpenId(value?: string): Promise<void> {
  const trimmed = value?.trim() ?? ''
  if (!trimmed) return Promise.resolve()
  if (trimmed.length < 8 || trimmed.length > 128) {
    return Promise.reject(new Error('飞书 open_id 长度须为 8–128 位'))
  }
  if (!/^ou[-_][A-Za-z0-9_-]+$/.test(trimmed)) {
    return Promise.reject(new Error('请输入以 ou_ 或 ou- 开头的 open_id'))
  }
  return Promise.resolve()
}

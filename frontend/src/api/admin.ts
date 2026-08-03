/** 系统管理 API（对应后端 app/api/v1/admin.py）：审计日志 + 系统配置。 */
import { request } from './http'

export interface AuditLog {
  id: string
  actor_id: string | null
  actor_role: string | null
  action: string
  target_type: string | null
  target_id: string | null
  summary: string
  detail: Record<string, unknown> | null
  result: string
  create_time: string
}

export interface SysConfig {
  key: string
  value: unknown
  value_type: string
  category: string
  is_editable: boolean
  is_secret: boolean
  is_set: boolean
}

export interface AuditLogPage {
  items: AuditLog[]
  total: number
}

export function listAuditLogs(params?: {
  action?: string
  actor_id?: string
  start?: string
  end?: string
  limit?: number
  offset?: number
}): Promise<AuditLogPage> {
  return request({ method: 'GET', url: '/audit-logs', params })
}

export function listConfigs(): Promise<SysConfig[]> {
  return request({ method: 'GET', url: '/configs' })
}

export function updateConfig(key: string, value: unknown): Promise<{ key: string; value: unknown }> {
  return request({ method: 'PATCH', url: `/configs/${key}`, data: { value } })
}

export interface ConnResult {
  target: string
  status: 'ok' | 'fail' | 'not_configured'
  latency_ms: number
  msg: string
}

export function testConnectivity(): Promise<ConnResult[]> {
  return request({ method: 'GET', url: '/admin/connectivity' })
}

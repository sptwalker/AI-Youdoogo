/** 数据接口 API（对应后端 app/api/v1/data_sources.py）。密钥仅回显状态位。 */
import { request } from './client'

export interface DataSource {
  id: string
  name: string
  code: string
  type: string
  department_id: string | null
  config: Record<string, unknown>
  secret_ref: string | null
  secret_status: 'not_set' | 'configured' | 'missing'
  is_active: boolean
  owner_agent_id: string | null
  owner_agent_name: string | null
}

export const DS_TYPES = ['thinkingdata', 'feishu_bitable', 'feishu_docx', 'excel', 'http_api']

export function listDataSources(): Promise<DataSource[]> {
  return request({ method: 'GET', url: '/data-sources' })
}

export function createDataSource(payload: {
  name: string
  type: string
  code?: string
  department_id?: string
  secret_ref?: string
  owner_agent_id?: string
}): Promise<{ id: string }> {
  return request({ method: 'POST', url: '/data-sources', data: payload })
}

export function updateDataSource(
  id: string,
  payload: {
    name?: string
    secret_ref?: string
    is_active?: boolean
    department_id?: string
    owner_agent_id?: string
  },
): Promise<{ id: string }> {
  return request({ method: 'PATCH', url: `/data-sources/${id}`, data: payload })
}

export function deleteDataSource(id: string): Promise<null> {
  return request({ method: 'DELETE', url: `/data-sources/${id}` })
}

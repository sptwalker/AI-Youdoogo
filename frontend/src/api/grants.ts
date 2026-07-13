/** 资源授权 API（对应后端 app/api/v1/grants.py）。grant 只授内容访问权，不授生效权。 */
import { request } from './client'

export interface ResourceGrant {
  id: string
  resource_type: string
  resource_id: string
  grantee_type: 'user' | 'agent' | 'department'
  grantee_id: string
  perm: string
  expires_at: string | null
  create_time: string
}

export function listGrants(params?: {
  resource_type?: string
  grantee_id?: string
}): Promise<ResourceGrant[]> {
  return request({ method: 'GET', url: '/resource-grants', params })
}

export function createGrant(payload: {
  resource_type: string
  resource_id: string
  grantee_type: string
  grantee_id: string
  perm?: string
}): Promise<{ id: string }> {
  return request({ method: 'POST', url: '/resource-grants', data: payload })
}

export function revokeGrant(id: string): Promise<null> {
  return request({ method: 'DELETE', url: `/resource-grants/${id}` })
}

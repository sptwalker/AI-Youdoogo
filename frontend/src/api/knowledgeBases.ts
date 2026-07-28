/** 知识库集合 API（对应后端 app/api/v1/knowledge_bases.py）。 */
import { request } from './http'

export interface KnowledgeBase {
  id: string
  name: string
  code: string
  scope: 'company' | 'department' | 'personal'
  department_id: string | null
  owner_agent_id: string | null
  is_confidential: boolean
  is_default: boolean
  is_active: boolean
  description: string | null
  file_count: number
}

export function listKnowledgeBases(): Promise<KnowledgeBase[]> {
  return request({ method: 'GET', url: '/knowledge-bases' })
}

export function createKnowledgeBase(payload: {
  name: string
  scope: string
  department_id?: string
  is_confidential?: boolean
  description?: string
}): Promise<{ id: string }> {
  return request({ method: 'POST', url: '/knowledge-bases', data: payload })
}

export function updateKnowledgeBase(
  id: string,
  payload: {
    name?: string
    is_confidential?: boolean
    description?: string
    is_active?: boolean
    department_id?: string
  },
): Promise<{ id: string }> {
  return request({ method: 'PATCH', url: `/knowledge-bases/${id}`, data: payload })
}

export function deleteKnowledgeBase(id: string): Promise<null> {
  return request({ method: 'DELETE', url: `/knowledge-bases/${id}` })
}

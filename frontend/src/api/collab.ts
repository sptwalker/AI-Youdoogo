/** 协作治理 API（对应后端 app/api/v1/collab.py）。桌面复核 + 发起协作请求。 */
import { request } from './http'

export function reviewCollab(
  id: string,
  decision: 'approve' | 'reject',
  note?: string,
): Promise<{ id: string; status: string }> {
  return request({ method: 'POST', url: `/collab-requests/${id}/review`, data: { decision, note } })
}

export function createCollabRequest(payload: {
  target_department_id: string
  title: string
  category?: string
  summary?: string
}): Promise<{ id: string; risk_level: string; status: string }> {
  return request({ method: 'POST', url: '/collab-requests', data: payload })
}

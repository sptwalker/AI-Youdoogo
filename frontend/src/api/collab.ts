/** 协作治理 API（对应后端 app/api/v1/collab.py）。 */
import { request } from './http'

export function reviewCollab(
  id: string,
  decision: 'approve' | 'reject',
  note?: string,
): Promise<{ id: string; status: string }> {
  return request({ method: 'POST', url: `/collab-requests/${id}/review`, data: { decision, note } })
}

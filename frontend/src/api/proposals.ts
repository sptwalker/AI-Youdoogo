/** 提案 API（对应后端 app/api/v1/proposals.py）。 */
import { request } from './http'

export interface Proposal {
  id: string
  code: string
  title: string
  background: string
  plan: string
  benefit_risk: string | null
  priority: string
  status: 'draft' | 'researching' | 'reviewed' | 'approved' | 'rejected'
  creator_id: string
  converted_task_id: string | null
  create_time: string
}

export interface Review {
  id: string
  review_type: 'ai_research' | 'human'
  conclusion: string
  reviewer_id: string | null
  decision: string | null
  create_time: string
}

export const PROPOSAL_STATUS: Record<string, string> = {
  draft: '草稿',
  researching: '预研中',
  reviewed: '已预研',
  approved: '已通过',
  rejected: '已驳回',
}

export function listProposals(status?: string): Promise<Proposal[]> {
  return request({ method: 'GET', url: '/proposals', params: status ? { status } : undefined })
}

export function getProposal(id: string): Promise<{ proposal: Proposal; reviews: Review[] }> {
  return request({ method: 'GET', url: `/proposals/${id}` })
}

export function createProposal(payload: {
  title: string
  background: string
  plan: string
  benefit_risk?: string
  priority?: string
}): Promise<Proposal> {
  return request({ method: 'POST', url: '/proposals', data: payload })
}

export function aiResearch(id: string): Promise<Review> {
  return request({ method: 'POST', url: `/proposals/${id}/ai-research` })
}

/** 编辑草稿提案（仅创建者本人、仅草稿状态可改，P3-7）。 */
export function editProposal(
  id: string,
  payload: { title: string; background: string; plan: string; benefit_risk?: string; priority?: string },
): Promise<Proposal> {
  return request({ method: 'PATCH', url: `/proposals/${id}`, data: payload })
}

/** 删除草稿提案（软删除，仅创建者本人、仅草稿状态可删，P3-7）。 */
export function deleteProposal(id: string): Promise<{ id: string }> {
  return request({ method: 'DELETE', url: `/proposals/${id}` })
}

export function reviewProposal(id: string, decision: 'approve' | 'reject', conclusion: string) {
  return request({ method: 'POST', url: `/proposals/${id}/review`, data: { decision, conclusion } })
}

export function convertProposal(id: string): Promise<unknown> {
  return request({ method: 'POST', url: `/proposals/${id}/convert`, data: {} })
}

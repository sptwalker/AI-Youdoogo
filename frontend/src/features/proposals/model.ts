import type { Proposal } from '../../api/proposals'

export function canResearchProposal(status: Proposal['status']): boolean {
  return status === 'draft' || status === 'reviewed'
}

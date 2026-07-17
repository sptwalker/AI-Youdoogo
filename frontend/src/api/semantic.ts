/** 业务术语字典 API（统一语义层，对应后端 app/api/v1/semantic.py）。 */
import { request } from './client'

export interface SemanticTerm {
  id: string
  canonical_name: string
  aliases: string[]
  term_type: 'metric' | 'dimension' | 'entity'
  definition: string | null
  linked_view: string | null
  sql_template: string | null
  kb_refs: string[]
  department_id: string | null
}

export type TermInput = Omit<SemanticTerm, 'id'>

export function listTerms(): Promise<SemanticTerm[]> {
  return request({ method: 'GET', url: '/semantic-terms' })
}

export function createTerm(body: Partial<TermInput>): Promise<SemanticTerm> {
  return request({ method: 'POST', url: '/semantic-terms', data: body })
}

export function updateTerm(id: string, body: Partial<TermInput>): Promise<SemanticTerm> {
  return request({ method: 'PUT', url: `/semantic-terms/${id}`, data: body })
}

export function deleteTerm(id: string): Promise<void> {
  return request({ method: 'DELETE', url: `/semantic-terms/${id}` })
}

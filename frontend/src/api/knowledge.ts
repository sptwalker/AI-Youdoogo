/** 知识库 API（对应后端 app/api/v1/knowledge.py）。 */
import { request } from './client'

export interface KnowledgeFile {
  id: string
  file_name: string
  category: string | null
  uploader_id: string
  file_size: number | null
  mime_type: string | null
  status: 'uploaded' | 'parsing' | 'indexed' | 'failed'
  create_time: string
}

export interface AskResponse {
  answer: string
  sources: Array<{ index: number; file_id: string; file_name: string; chunk_index: number }>
}

export function listKnowledgeFiles(): Promise<KnowledgeFile[]> {
  return request({ method: 'GET', url: '/knowledge/files' })
}

export function ingestText(payload: {
  title: string
  text: string
  category?: string
  knowledge_base_id?: string
}): Promise<KnowledgeFile> {
  return request({ method: 'POST', url: '/knowledge/text', data: payload })
}

export function ingestFeishu(payload: {
  document_id: string
  category?: string
  knowledge_base_id?: string
}): Promise<KnowledgeFile> {
  return request({ method: 'POST', url: '/knowledge/feishu', data: payload })
}

export function uploadKnowledgeFile(
  file: File,
  opts?: { category?: string; knowledgeBaseId?: string },
): Promise<KnowledgeFile> {
  const form = new FormData()
  form.append('file', file)
  if (opts?.category) form.append('category', opts.category)
  if (opts?.knowledgeBaseId) form.append('knowledge_base_id', opts.knowledgeBaseId)
  return request({ method: 'POST', url: '/knowledge/files', data: form })
}

export function deleteKnowledgeFile(id: string): Promise<null> {
  return request({ method: 'DELETE', url: `/knowledge/files/${id}` })
}

export function moveKnowledgeFile(id: string, knowledgeBaseId: string): Promise<KnowledgeFile> {
  return request({
    method: 'PATCH',
    url: `/knowledge/files/${id}/move`,
    data: { knowledge_base_id: knowledgeBaseId },
  })
}

export function askKnowledge(query: string, topK = 5): Promise<AskResponse> {
  return request({ method: 'POST', url: '/knowledge/ask', data: { query, top_k: topK } })
}

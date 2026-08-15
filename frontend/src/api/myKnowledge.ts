/** 个人知识中枢 API（对应后端 app/api/v1/my_knowledge.py，owner 恒为登录用户）。
 *
 *  隔离：路由不接受客户端 knowledge_base_id，检索/问答只在本人个人库内 → 跨人不可见。
 *  类型复用 knowledge.ts 的 KnowledgeFile / AskResponse（同一 FileOut / AskResponse schema）。 */
import { request } from './http'
import type { AskResponse, KnowledgeFile } from './knowledge'

export interface SearchHit {
  file_id: string
  file_name: string
  chunk_index: number
  score_distance: number
  snippet: string
}

export function listMyDocuments(limit = 100): Promise<KnowledgeFile[]> {
  return request({ method: 'GET', url: '/my-knowledge/documents', params: { limit } })
}

export function ingestMyText(payload: {
  title: string
  text: string
  category?: string
}): Promise<KnowledgeFile> {
  return request({ method: 'POST', url: '/my-knowledge/documents', data: payload })
}

export function searchMyKnowledge(
  query: string,
  topK = 5,
): Promise<{ query: string; hits: SearchHit[] }> {
  return request({ method: 'POST', url: '/my-knowledge/search', data: { query, top_k: topK } })
}

export function askMyKnowledge(query: string, topK = 5): Promise<AskResponse> {
  return request({ method: 'POST', url: '/my-knowledge/ask', data: { query, top_k: topK } })
}

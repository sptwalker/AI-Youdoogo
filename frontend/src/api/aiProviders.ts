/** AI 模型卡片 API（对应后端 app/api/v1/ai_providers.py）。密钥仅回显 hint + 状态位。 */
import { request } from './client'

export type Tier = 'daily' | 'reasoning'
export type TestStatus = 'ok' | 'fail' | 'untested' | 'disabled'

export interface AiProvider {
  id: string
  name: string
  tier: Tier
  base_url: string
  model: string
  api_key_hint: string
  api_key_set: boolean
  is_primary: boolean
  is_active: boolean
  last_test_status: TestStatus
  last_test_at: string | null
  last_test_latency_ms: number | null
  last_test_msg: string | null
}

export interface TestResult {
  status: TestStatus
  latency_ms: number | null
  msg: string
}

export const TIER_LABEL: Record<Tier, string> = { daily: '日常', reasoning: '推理' }

export function listProviders(): Promise<AiProvider[]> {
  return request({ method: 'GET', url: '/ai-providers' })
}

export function createProvider(payload: {
  name: string
  tier: Tier
  base_url: string
  api_key: string
  model: string
}): Promise<{ id: string }> {
  return request({ method: 'POST', url: '/ai-providers', data: payload })
}

export function updateProvider(
  id: string,
  payload: Partial<{ name: string; tier: Tier; base_url: string; api_key: string; model: string }>,
): Promise<{ id: string }> {
  return request({ method: 'PATCH', url: `/ai-providers/${id}`, data: payload })
}

export function deleteProvider(id: string): Promise<null> {
  return request({ method: 'DELETE', url: `/ai-providers/${id}` })
}

export function testProvider(id: string): Promise<TestResult> {
  return request({ method: 'POST', url: `/ai-providers/${id}/test` })
}

export function setPrimary(id: string): Promise<{ id: string }> {
  return request({ method: 'POST', url: `/ai-providers/${id}/primary` })
}

export function toggleActive(id: string, active: boolean): Promise<{ id: string; is_active: boolean }> {
  return request({ method: 'POST', url: `/ai-providers/${id}/toggle`, data: { active } })
}

export function testAll(): Promise<Array<{ id: string } & TestResult>> {
  return request({ method: 'POST', url: '/ai-providers/test-all' })
}

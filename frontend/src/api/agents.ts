/** 智能体 API（对应后端 app/api/v1/agents.py）。 */
import { request } from './client'

export interface TaskRecord {
  id: string
  agent_role_id: string
  task_type: string
  input_summary: string | null
  output_content: string | null
  model_used: string | null
  status: 'success' | 'failed'
  error_msg: string | null
  duration_ms: number | null
  create_time: string
}

export interface AgentRole {
  id: string
  name: string
  duty: string | null
  model_role: string
  permission_scope: Record<string, unknown>
  tools: unknown[]
  is_active: boolean
}

export interface Alert {
  product: string
  metric: string
  severity: string
  message: string
}

/** rows 省略时后端按 stat_date 从已入库指标取数。 */
export function generateDailyReport(stat_date: string): Promise<TaskRecord> {
  return request({ method: 'POST', url: '/agents/ops/daily-report', data: { stat_date } })
}

export function anomalyCheck(
  stat_date: string,
): Promise<{ alerts: Alert[]; record: TaskRecord | null }> {
  return request({ method: 'POST', url: '/agents/ops/anomaly-check', data: { stat_date } })
}

export function generateProposal(topic: string, context = ''): Promise<TaskRecord> {
  return request({ method: 'POST', url: '/agents/ops/proposal', data: { topic, context } })
}

export function listRecords(limit = 20): Promise<TaskRecord[]> {
  return request({ method: 'GET', url: '/agents/records', params: { limit } })
}

export function listRoles(): Promise<AgentRole[]> {
  return request({ method: 'GET', url: '/agents/roles' })
}

export function addFeedback(recordId: string, score: number, comment?: string) {
  return request({
    method: 'POST',
    url: `/agents/records/${recordId}/feedback`,
    data: { score, comment },
  })
}

export interface OptimizeResult {
  role_id: string
  current_prompt: string
  suggested_prompt: string
  based_on_samples: number
}

export function optimizePrompt(roleId: string): Promise<OptimizeResult> {
  return request({ method: 'POST', url: `/agents/roles/${roleId}/optimize-prompt` })
}

export function updateRolePrompt(roleId: string, prompt_template: string) {
  return request({ method: 'PATCH', url: `/agents/roles/${roleId}`, data: { prompt_template } })
}

/** AI 任务中心 API（对应后端 app/api/v1/ai_tasks.py）：先出计划（NL→DAG）供真人确认，再执行。 */
import { request } from './http'
import type { OrchProgress } from './tasks'

export interface PlanStep {
  number: number
  title: string
  capability_key: string
  instruction: string
  depends_on: number[]
}

export interface PlanPreview {
  title: string | null
  request: string
  steps: PlanStep[]
}

/** NL → 计划预览。plan=null 表示非多步（reason 说明原因），前端提示走普通任务卡。 */
export function planAiTask(payload: { request: string; title?: string }): Promise<{
  plan: PlanPreview | null
  reason: string | null
}> {
  return request({ method: 'POST', url: '/ai-tasks/plan', data: payload })
}

/** 执行真人已确认的计划（回传步骤，后端复校 DAG）→ 返回编排进度快照。 */
export function executeAiTask(payload: {
  request: string
  title?: string
  steps: PlanStep[]
}): Promise<OrchProgress> {
  return request({ method: 'POST', url: '/ai-tasks/execute', data: payload })
}

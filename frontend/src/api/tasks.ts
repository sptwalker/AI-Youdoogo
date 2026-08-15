/** 任务卡 API（对应后端 app/api/v1/tasks.py）。 */
import { request } from './http'

export interface TaskCard {
  id: string
  title: string
  task_type: string
  priority: string
  status: TaskStatus
  creator_id: string
  assignee_agent_id: string | null
  parent_id: string | null
  sla_hours: number | null
  result_content: string | null
  create_time: string
  project_id: string | null
  archived_at: string | null
  /** 只读派生：看板泳道（待启动/进行中/待审核/已完成/驳回/已终止/已归档）。 */
  lane: string
  /** 只读派生：进行中且陈旧/等待 → 需关注。 */
  blocked: boolean
}

export type TaskStatus =
  | 'created'
  | 'dispatched'
  | 'executing'
  | 'reported'
  | 'accepted'
  | 'rejected'
  | 'cancelled'

export const STATUS_LABEL: Record<string, string> = {
  created: '已创建',
  dispatched: '已分发',
  executing: '执行中',
  reported: '已汇报',
  accepted: '已验收',
  rejected: '已驳回',
  cancelled: '已终止',
}

export function listTasks(status?: string): Promise<TaskCard[]> {
  return request({ method: 'GET', url: '/tasks', params: status ? { status } : undefined })
}

export function createTask(payload: {
  title: string
  task_type: string
  priority?: string
  assignee_agent_id?: string
  sla_hours?: number
}): Promise<TaskCard> {
  return request({ method: 'POST', url: '/tasks', data: payload })
}

export function transitionTask(
  id: string,
  to_status: TaskStatus,
  note?: string,
): Promise<TaskCard> {
  return request({ method: 'POST', url: `/tasks/${id}/transition`, data: { to_status, note } })
}

export function runTask(id: string): Promise<TaskCard> {
  return request({ method: 'POST', url: `/tasks/${id}/run` })
}

/** 编辑/补指派未开跑任务（created/rejected），留空字段不改（P2-12）。 */
export function editTask(
  id: string,
  payload: { title?: string; priority?: string; assignee_agent_id?: string },
): Promise<TaskCard> {
  return request({ method: 'PATCH', url: `/tasks/${id}`, data: payload })
}

// ── 任务编排进度（docs/14 阶段B）──────────────────────────
interface OrchStep {
  id: string
  step_no: number
  title: string
  skill: string
  status: string
  red_line: boolean
}

export interface OrchProgress {
  parent_id: string
  total: number
  accepted: number
  awaiting_human: string[]
  done: boolean
  steps: OrchStep[]
}

/** 拉取某编排父卡的进度快照（进度卡刷新用）。 */
export function getOrchestrationProgress(parentId: string): Promise<OrchProgress> {
  return request({ method: 'GET', url: `/tasks/${parentId}/orchestration` })
}

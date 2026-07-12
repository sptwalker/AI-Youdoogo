/** 任务卡 API（对应后端 app/api/v1/tasks.py）。 */
import { request } from './client'

export interface TaskCard {
  id: string
  title: string
  task_type: string
  priority: string
  status: string
  creator_id: string
  assignee_agent_id: string | null
  parent_id: string | null
  sla_hours: number | null
  result_content: string | null
  create_time: string
}

export interface TaskLog {
  id: string
  from_status: string | null
  to_status: string
  operator_id: string | null
  note: string | null
  create_time: string
}

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

export function getTask(id: string): Promise<{ task: TaskCard; logs: TaskLog[] }> {
  return request({ method: 'GET', url: `/tasks/${id}` })
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
  to_status: string,
  note?: string,
): Promise<TaskCard> {
  return request({ method: 'POST', url: `/tasks/${id}/transition`, data: { to_status, note } })
}

export function runTask(id: string): Promise<TaskCard> {
  return request({ method: 'POST', url: `/tasks/${id}/run` })
}

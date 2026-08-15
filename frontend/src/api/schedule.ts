/** 个人日程 API（对应后端 app/api/v1/schedule.py，owner 恒为登录用户）。
 *
 *  隔离：只读/确认均按本人 owner_id；确认命中他人 → 404。
 *  红线：智能排程只出建议（suggested），confirm 才生效。 */
import { request } from './http'

export interface Schedule {
  id: string
  title: string
  start_at: string
  end_at: string
  source: string
  status: 'suggested' | 'confirmed' | 'done' | 'cancelled'
  linked_task_id: string | null
  create_time: string
}

export const SCHEDULE_STATUS: Record<string, string> = {
  suggested: '建议',
  confirmed: '已确认',
  done: '已完成',
  cancelled: '已取消',
}

export function listSchedules(status?: string): Promise<Schedule[]> {
  return request({ method: 'GET', url: '/schedules', params: status ? { status } : undefined })
}

export function confirmSchedule(id: string): Promise<Schedule> {
  return request({ method: 'POST', url: `/schedules/${id}/confirm` })
}

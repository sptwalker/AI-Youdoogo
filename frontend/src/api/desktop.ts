/** 真人工作桌面 API（对应后端 app/api/v1/desktop.py）。取代 workbench。 */
import { request } from './client'

export interface PendingItem {
  kind: 'task' | 'proposal' | 'resolution' | 'collab'
  id: string
  title: string
  meta: string | null
  priority: string
  create_time: string
}

export interface MyTask {
  id: string
  title: string
  task_type: string
  status: string
  priority: string
  create_time: string
}

export interface Desktop {
  user: { id: string; name: string; role_code: string }
  pending: PendingItem[]
  pending_count: number
  my_tasks: MyTask[]
  counts: { channels: number; kbs: number }
}

/** 我的桌面；传 userId 则由 admin 查看他人（监督）。 */
export function getDesktop(userId?: string): Promise<Desktop> {
  return request({ method: 'GET', url: userId ? `/desktop/${userId}` : '/desktop' })
}

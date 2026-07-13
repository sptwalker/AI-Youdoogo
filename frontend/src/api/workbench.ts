/** 真人工作台 API（对应后端 app/api/v1/workbench.py）。聚合三个「待我确认」队列。 */
import { request } from './client'

export interface WbTask {
  id: string
  title: string
  task_type: string
  priority: string
  create_time: string
}

export interface WbProposal {
  id: string
  code: string
  title: string
  priority: string
  department_id: string | null
  create_time: string
}

export interface WbResolution {
  id: string
  meeting_id: string
  content: string
  due_date: string | null
  create_time: string
}

export interface Workbench {
  counts: { tasks: number; proposals: number; resolutions: number }
  tasks: WbTask[]
  proposals: WbProposal[]
  resolutions: WbResolution[]
}

export function getWorkbench(): Promise<Workbench> {
  return request({ method: 'GET', url: '/workbench' })
}

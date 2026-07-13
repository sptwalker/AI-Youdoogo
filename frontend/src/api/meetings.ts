/** 会议 API（对应后端 app/api/v1/meetings.py）。 */
import { request } from './client'

export interface Meeting {
  id: string
  title: string
  meeting_type: string
  status: 'scheduled' | 'in_progress' | 'closed'
  creator_id: string
  summary: string | null
  create_time: string
}

export interface Discuss {
  id: string
  speaker_type: 'human' | 'ai'
  speaker_name: string
  content: string
  create_time: string
}

export interface Resolution {
  id: string
  content: string
  owner_id: string | null
  due_date: string | null
  is_confirmed: boolean
  confirmed_by: string | null
  converted_task_id: string | null
  create_time: string
}

export const MEETING_STATUS: Record<string, string> = {
  scheduled: '待开始',
  in_progress: '进行中',
  closed: '已结束',
}

export function listMeetings(): Promise<Meeting[]> {
  return request({ method: 'GET', url: '/meetings' })
}

export function getMeeting(
  id: string,
): Promise<{ meeting: Meeting; discussions: Discuss[]; resolutions: Resolution[] }> {
  return request({ method: 'GET', url: `/meetings/${id}` })
}

export function createMeeting(title: string): Promise<Meeting> {
  return request({ method: 'POST', url: '/meetings', data: { title } })
}

export function setMeetingStatus(id: string, to_status: 'in_progress' | 'closed') {
  return request({ method: 'POST', url: `/meetings/${id}/status`, data: { to_status } })
}

export function discuss(id: string, content: string) {
  return request({ method: 'POST', url: `/meetings/${id}/discuss`, data: { content } })
}

export function aiSpeak(id: string, topic: string) {
  return request({ method: 'POST', url: `/meetings/${id}/ai-speak`, data: { topic } })
}

export function vote(id: string, subject: string, choice: string) {
  return request({ method: 'POST', url: `/meetings/${id}/vote`, data: { subject, choice } })
}

export function aiVote(id: string, subject: string) {
  return request({ method: 'POST', url: `/meetings/${id}/ai-vote`, data: { subject } })
}

export interface Tally {
  subject: string
  human: Record<string, number>
  ai: Record<string, number>
  human_passed: boolean
}

export function getTally(id: string, subject: string): Promise<Tally> {
  return request({ method: 'GET', url: `/meetings/${id}/tally`, params: { subject } })
}

export function generateMinutes(id: string): Promise<Meeting> {
  return request({ method: 'POST', url: `/meetings/${id}/minutes` })
}

export function createResolution(id: string, content: string): Promise<Resolution> {
  return request({ method: 'POST', url: `/meetings/${id}/resolutions`, data: { content } })
}

export function confirmResolution(rid: string): Promise<Resolution> {
  return request({ method: 'POST', url: `/meetings/resolutions/${rid}/confirm` })
}

export function convertResolution(rid: string): Promise<unknown> {
  return request({ method: 'POST', url: `/meetings/resolutions/${rid}/convert`, data: {} })
}

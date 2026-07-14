/** 协作空间 API（对应后端 app/api/v1/discussion.py）。 */
import { request, sseRequest, type SseHandler } from './client'

export interface Channel {
  id: string
  name: string
  department_id: string | null
  default_agent_id: string | null
  is_archived: boolean
  create_time: string
}

export interface Message {
  id: string
  channel_id: string
  speaker_type: 'human' | 'ai'
  speaker_id: string | null
  speaker_name: string
  content: string
  mentioned_agent_ids: string[]
  ai_source_record_id: string | null
  ref_type: string | null
  ref_id: string | null
  create_time: string
}

export function listChannels(departmentId?: string): Promise<Channel[]> {
  return request({
    method: 'GET',
    url: '/channels',
    params: departmentId ? { department_id: departmentId } : undefined,
  })
}

export function createChannel(payload: {
  name: string
  department_id?: string
  default_agent_id?: string
}): Promise<{ id: string; name: string }> {
  return request({ method: 'POST', url: '/channels', data: payload })
}

export function listMessages(channelId: string): Promise<Message[]> {
  return request({ method: 'GET', url: `/channels/${channelId}/messages` })
}

/** 发言，SSE 逐字流式回调：message_end(真人消息) → 每个 @AI 依次
 *  message_start → delta* → message_end。 */
export function postMessage(
  channelId: string,
  content: string,
  mentioned_agent_ids: string[],
  onEvent: SseHandler,
): Promise<void> {
  return sseRequest(`/channels/${channelId}/messages`, { content, mentioned_agent_ids }, onEvent)
}

export function promoteMessage(
  messageId: string,
  target: 'proposal' | 'task',
): Promise<{ ref_type: string; ref_id: string }> {
  return request({ method: 'POST', url: `/messages/${messageId}/promote`, data: { target } })
}

/** 协作空间 API（对应后端 app/api/v1/discussion.py）。 */
import { request, sseRequest, sseSubscribe, TOKEN_KEY, type SseHandler } from './client'

export interface Channel {
  id: string
  name: string
  department_id: string | null
  default_agent_id: string | null
  creator_id: string | null
  is_archived: boolean
  create_time: string
}

export interface Attachment {
  type: 'image' | 'file'
  name: string
  storage_path: string
  size: number
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
  attachments?: Attachment[]
  create_time: string
}

export interface ChannelWithUnread extends Channel {
  unread: number
}

/** 我的群 + 未读数（I5，话题页签用）。 */
export function myChannels(): Promise<ChannelWithUnread[]> {
  return request({ method: 'GET', url: '/channels/mine' })
}

/** 某群未读清零（进群/读消息时，I5）。 */
export function markRead(channelId: string): Promise<null> {
  return request({ method: 'POST', url: `/channels/${channelId}/read` })
}

/** 群成员名单（I4）。 */
export function listMembers(channelId: string): Promise<{ member_type: string; member_id: string; member_name: string }[]> {
  return request({ method: 'GET', url: `/channels/${channelId}/members` })
}

/** 加成员（真人+AI 混合，I4）。 */
export function addMembers(
  channelId: string,
  members: { member_type: 'human' | 'ai'; member_id: string; member_name?: string }[],
): Promise<{ added: number }> {
  return request({ method: 'POST', url: `/channels/${channelId}/members`, data: { members } })
}

/** 踢出成员（仅群主）。 */
export function removeMember(channelId: string, memberType: string, memberId: string): Promise<null> {
  return request({ method: 'DELETE', url: `/channels/${channelId}/members/${memberType}/${memberId}` })
}

/** 解散讨论群（仅群主）。 */
export function disbandChannel(channelId: string): Promise<null> {
  return request({ method: 'DELETE', url: `/channels/${channelId}` })
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
  members?: { member_type: 'human' | 'ai'; member_id: string; member_name?: string }[]
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
  attachments: Attachment[] = [],
): Promise<void> {
  return sseRequest(`/channels/${channelId}/messages`, { content, mentioned_agent_ids, attachments }, onEvent)
}

/** 上传群聊附件（图片/文件，I6）→ 返回附件元数据。 */
export async function uploadAttachment(file: File): Promise<Attachment> {
  const form = new FormData()
  form.append('file', file)
  return request({ method: 'POST', url: '/channels/attachments', data: form })
}

/** 群聊附件下载地址（带鉴权由前端 fetch，见 downloadAttachment）。 */
export async function downloadAttachment(att: Attachment): Promise<void> {
  const token = localStorage.getItem(TOKEN_KEY)
  const url = `/api/v1/channels/attachments/download?storage_path=${encodeURIComponent(att.storage_path)}&name=${encodeURIComponent(att.name)}`
  const resp = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
  if (!resp.ok) throw new Error('下载失败')
  const blob = await resp.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = att.name
  a.click()
  URL.revokeObjectURL(a.href)
}

/** 订阅实时消息推送（I3）。别人在群发言即时收到。返回取消函数。 */
export function subscribeRealtime(onEvent: SseHandler): () => void {
  return sseSubscribe('/channels/realtime/stream', onEvent)
}

export function promoteMessage(
  messageId: string,
  target: 'proposal' | 'task',
): Promise<{ ref_type: string; ref_id: string }> {
  return request({ method: 'POST', url: `/messages/${messageId}/promote`, data: { target } })
}

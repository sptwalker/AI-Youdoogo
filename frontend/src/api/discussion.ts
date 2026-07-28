/** 协作空间 API（对应后端 app/api/v1/discussion.py）。 */
import { message } from 'antd'
import {
  ApiError,
  clearSessionAndRedirectToLogin,
  request,
  sseRequest,
  sseSubscribe,
  TOKEN_KEY,
  type SseConnectionState,
  type SseHandler,
  type SseRequestOptions,
  type SseSubscription,
} from './http'

export interface DiscussionRequestOptions {
  signal?: AbortSignal
  silent?: boolean
}

interface Channel {
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

export interface RealtimeMessageEvent {
  type: 'message'
  payload: Message
}

export interface ChannelWithUnread extends Channel {
  unread: number
}

export function parseRealtimeMessageEvent(
  event: string,
  data: Record<string, unknown>,
): RealtimeMessageEvent | null {
  if (event !== 'message') return null
  return { type: 'message', payload: data as unknown as Message }
}

/** 我的群 + 未读数（I5，话题页签用）。 */
export function myChannels(options: DiscussionRequestOptions = {}): Promise<ChannelWithUnread[]> {
  return request({ method: 'GET', url: '/channels/mine', ...options })
}

/** 某群未读清零（进群/读消息时，I5）。 */
export function markRead(channelId: string, options: DiscussionRequestOptions = {}): Promise<null> {
  return request({ method: 'POST', url: `/channels/${channelId}/read`, ...options })
}

/** 群成员名单（I4）。 */
export function listMembers(
  channelId: string,
  options: DiscussionRequestOptions = {},
): Promise<{ member_type: string; member_id: string; member_name: string }[]> {
  return request({ method: 'GET', url: `/channels/${channelId}/members`, ...options })
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

export function createChannel(payload: {
  name: string
  department_id?: string
  default_agent_id?: string
  members?: { member_type: 'human' | 'ai'; member_id: string; member_name?: string }[]
}): Promise<{ id: string; name: string }> {
  return request({ method: 'POST', url: '/channels', data: payload })
}

export function listMessages(channelId: string, options: DiscussionRequestOptions = {}): Promise<Message[]> {
  return request({ method: 'GET', url: `/channels/${channelId}/messages`, ...options })
}

/** 发言，SSE 逐字流式回调：message_end(真人消息) → 每个 @AI 依次
 *  message_start → delta* → message_end。 */
export function postMessage(
  channelId: string,
  content: string,
  mentioned_agent_ids: string[],
  onEvent: SseHandler,
  attachments: Attachment[] = [],
  options?: SseRequestOptions,
): Promise<void> {
  return sseRequest(
    `/channels/${channelId}/messages`,
    { content, mentioned_agent_ids, attachments },
    onEvent,
    options,
  )
}

/** 上传群聊附件（图片/文件，I6）→ 返回附件元数据。 */
export async function uploadAttachment(file: File): Promise<Attachment> {
  const form = new FormData()
  form.append('file', file)
  return request({ method: 'POST', url: '/channels/attachments', data: form })
}

function attachmentDownloadUrl(att: Attachment): string {
  return `/api/v1/channels/attachments/download?storage_path=${encodeURIComponent(att.storage_path)}&name=${encodeURIComponent(att.name)}`
}

/** 附件二进制内容；图片预览与文件下载都必须手动带 Bearer token。 */
export async function fetchAttachmentBlob(
  att: Attachment,
  options: { signal?: AbortSignal; silent?: boolean } = {},
): Promise<Blob> {
  const token = localStorage.getItem(TOKEN_KEY)
  const resp = await fetch(attachmentDownloadUrl(att), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal: options.signal,
  })
  if (resp.status === 401) {
    const redirected = clearSessionAndRedirectToLogin()
    if (!redirected && !options.silent) message.error('未登录或登录已过期')
    throw new ApiError('未登录或登录已过期')
  }
  if (!resp.ok) {
    let errorMessage = '附件读取失败'
    try {
      const body = await resp.json() as { msg?: string; detail?: string }
      errorMessage = body.msg ?? body.detail ?? errorMessage
    } catch { /* 非 JSON 错误体 */ }
    if (!options.silent) message.error(errorMessage)
    throw new ApiError(errorMessage)
  }
  return resp.blob()
}

/** 群聊附件下载。 */
export async function downloadAttachment(att: Attachment): Promise<void> {
  const blob = await fetchAttachmentBlob(att)
  const a = document.createElement('a')
  const url = URL.createObjectURL(blob)
  a.href = url
  a.download = att.name
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

/** 订阅实时消息推送（I3）。别人在群发言即时收到，并暴露连接状态供轮询降级。 */
export function subscribeRealtime(
  onEvent: SseHandler,
  onStateChange?: (state: SseConnectionState) => void,
): SseSubscription {
  return sseSubscribe('/channels/realtime/stream', onEvent, { onStateChange })
}

export function promoteMessage(
  messageId: string,
  target: 'proposal' | 'task',
): Promise<{ ref_type: string; ref_id: string }> {
  return request({ method: 'POST', url: `/messages/${messageId}/promote`, data: { target } })
}

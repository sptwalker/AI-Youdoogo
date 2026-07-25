/** 真人工作桌面 API（对应后端 app/api/v1/desktop.py）。取代 workbench。 */
import { message } from 'antd'
import {
  ApiError,
  clearSessionAndRedirectToLogin,
  request,
  sseRequest,
  TOKEN_KEY,
  type SseHandler,
  type SseRequestOptions,
} from './client'
import type { Attachment } from './discussion'

export type { Attachment } from './discussion'

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

// ── 工作桌面对话（专属助理 + 圆桌多AI）──────────────────────────
export interface ReplyPreview {
  id: string
  speaker_name: string
  content: string
}

export interface DesktopMessage {
  id: string
  speaker_type: 'user' | 'ai'
  speaker_agent_id: string | null
  speaker_name: string
  content: string
  create_time: string
  reply_to_message_id: string | null
  reply_preview: ReplyPreview | null
  attachments: Attachment[]
  is_pinned: boolean
  pinned_at: string | null
  pinned_by_user_id: string | null
}

export interface AddableAgent {
  id: string
  name: string
  title: string
}

export interface DesktopChat {
  assistant: { id: string; name: string }
  messages: DesktopMessage[]
  addable_agents: AddableAgent[]
}

/** 我的助理对话（默认助理 + 最近N天历史 + 可加入的AI）。 */
export function getDesktopChat(): Promise<DesktopChat> {
  return request({ method: 'GET', url: '/desktop/chat' })
}

/** 发一条消息（可再加最多2个AI圆桌讨论），SSE 逐字流式回调：
 *  message_end(用户回显) → 每个 AI 依次 message_start → delta* → message_end。 */
export function sendDesktopChat(
  payload: {
    message: string
    addAgentIds: string[]
    replyToMessageId?: string | null
    attachments?: Attachment[]
  },
  onEvent: SseHandler,
  options?: SseRequestOptions,
): Promise<void> {
  return sseRequest(
    '/desktop/chat',
    {
      message: payload.message,
      add_agent_ids: payload.addAgentIds,
      reply_to_message_id: payload.replyToMessageId ?? undefined,
      attachments: payload.attachments ?? [],
    },
    onEvent,
    options,
  )
}

/** 上传桌面对话附件（图片/文件）→ 返回附件元数据。 */
export async function uploadDesktopAttachment(file: File): Promise<Attachment> {
  const form = new FormData()
  form.append('file', file)
  return request({ method: 'POST', url: '/desktop/chat/attachments', data: form })
}

function desktopAttachmentUrl(att: Attachment): string {
  return `/api/v1/desktop/chat/attachments/download?storage_path=${encodeURIComponent(att.storage_path)}&name=${encodeURIComponent(att.name)}`
}

async function fetchProtectedBlob(url: string, defaultErrorMessage = '下载失败'): Promise<Blob> {
  const token = localStorage.getItem(TOKEN_KEY)
  const resp = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (resp.status === 401) {
    if (!clearSessionAndRedirectToLogin()) message.error('未登录或登录已过期')
    throw new ApiError('未登录或登录已过期')
  }
  if (!resp.ok) {
    let errorMessage = defaultErrorMessage
    try {
      const body = await resp.json() as { msg?: string; detail?: string }
      errorMessage = body.msg ?? body.detail ?? errorMessage
    } catch {
      // 非 JSON 错误体
    }
    message.error(errorMessage)
    throw new ApiError(errorMessage)
  }
  return resp.blob()
}

function triggerBlobDownload(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = fileName
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

/** 拉取桌面对话附件二进制，供图片预览和下载复用。 */
export async function fetchDesktopAttachment(att: Attachment): Promise<Blob> {
  return fetchProtectedBlob(desktopAttachmentUrl(att))
}

/** 下载桌面对话附件：Bearer 在 header 无法用 <a href> 直链，故 fetch 取 blob 触发保存。 */
export async function downloadDesktopAttachment(att: Attachment): Promise<void> {
  const blob = await fetchDesktopAttachment(att)
  triggerBlobDownload(blob, att.name)
}

export function pinDesktopMessage(messageId: string): Promise<DesktopMessage> {
  return request({ method: 'POST', url: '/desktop/chat/pin', data: { message_id: messageId } })
}

export function unpinDesktopMessage(messageId: string): Promise<DesktopMessage> {
  return request({ method: 'POST', url: '/desktop/chat/unpin', data: { message_id: messageId } })
}

// ── 文件交付区（AI 交付的文档/表格）──────────────────────────
export interface Deliverable {
  id: string
  file_name: string
  file_format: 'csv' | 'xlsx' | 'md' | 'txt'
  agent_name: string
  file_size: number
  create_time: string
}

/** 我的交付区文件（AI 交付的文档/表格，最近优先）。 */
export function listDeliverables(userId?: string): Promise<Deliverable[]> {
  return request({
    method: 'GET',
    url: '/desktop/deliverables',
    params: userId ? { user_id: userId } : undefined,
  })
}

/** 下载一份交付物：Bearer 在 header 无法用 <a href> 直链，故 fetch 取 blob 触发保存。 */
export async function downloadDeliverable(id: string, fileName: string): Promise<void> {
  const blob = await fetchProtectedBlob(`/api/v1/desktop/deliverables/${id}/download`)
  triggerBlobDownload(blob, fileName)
}

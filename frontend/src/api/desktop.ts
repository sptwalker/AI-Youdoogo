/** 真人工作桌面 API（对应后端 app/api/v1/desktop.py）。取代 workbench。 */
import { request, sseRequest, type SseHandler } from './client'

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
export interface DesktopMessage {
  id: string
  speaker_type: 'user' | 'ai'
  speaker_agent_id: string | null
  speaker_name: string
  content: string
  create_time: string
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
  message: string,
  addAgentIds: string[],
  onEvent: SseHandler,
): Promise<void> {
  return sseRequest('/desktop/chat', { message, add_agent_ids: addAgentIds }, onEvent)
}

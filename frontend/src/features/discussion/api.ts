import { listRoles, type AgentRole } from '../../api/agents'
import { roster, type Colleague } from '../../api/auth'
import {
  addMembers,
  createChannel,
  disbandChannel,
  downloadAttachment,
  listMembers,
  listMessages,
  markRead,
  myChannels,
  postMessage,
  promoteMessage,
  removeMember,
  subscribeRealtime,
  uploadAttachment,
  type Attachment,
  type ChannelWithUnread,
  type DiscussionRequestOptions,
  type Message,
} from '../../api/discussion'
import type { SseHandler } from '../../api/client'

export type { AgentRole, Attachment, Colleague, Message }
export type { ChannelWithUnread }

export interface DiscussionMember {
  member_type: string
  member_id: string
  member_name: string
}

export interface MemberToAdd {
  member_type: 'human' | 'ai'
  member_id: string
  member_name?: string
}

export interface GroupChatApi {
  listAgents(): Promise<AgentRole[]>
  listColleagues(): Promise<Colleague[]>
  listMembers(channelId: string, options?: DiscussionRequestOptions): Promise<DiscussionMember[]>
  addMembers(channelId: string, members: MemberToAdd[]): Promise<{ added: number }>
  removeMember(channelId: string, memberType: string, memberId: string): Promise<null>
  disbandChannel(channelId: string): Promise<null>
  listMessages(channelId: string, options?: DiscussionRequestOptions): Promise<Message[]>
  markRead(channelId: string, options?: DiscussionRequestOptions): Promise<null>
  postMessage(
    channelId: string,
    content: string,
    mentionedAgentIds: string[],
    onEvent: SseHandler,
    attachments?: Attachment[],
  ): Promise<void>
  uploadAttachment(file: File): Promise<Attachment>
  downloadAttachment(attachment: Attachment): Promise<void>
}

export const groupChatApi: GroupChatApi = {
  listAgents: listRoles,
  listColleagues: roster,
  listMembers,
  addMembers,
  removeMember,
  disbandChannel,
  listMessages,
  markRead,
  postMessage,
  uploadAttachment,
  downloadAttachment,
}

export interface DiscussionWorkspaceApi extends GroupChatApi {
  listChannels(options?: DiscussionRequestOptions): Promise<ChannelWithUnread[]>
  createChannel(payload: {
    name: string
    members: MemberToAdd[]
  }): Promise<{ id: string; name: string }>
  subscribeRealtime: typeof subscribeRealtime
  promoteMessage(
    messageId: string,
    target: 'proposal' | 'task',
  ): Promise<{ ref_type: string; ref_id: string }>
}

export const discussionWorkspaceApi: DiscussionWorkspaceApi = {
  ...groupChatApi,
  listChannels: myChannels,
  createChannel,
  subscribeRealtime,
  promoteMessage,
}

export function attachmentPreviewUrl(attachment: Attachment): string {
  const storagePath = encodeURIComponent(attachment.storage_path)
  const name = encodeURIComponent(attachment.name)
  return `/api/v1/channels/attachments/download?storage_path=${storagePath}&name=${name}`
}

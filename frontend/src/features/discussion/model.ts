import type {
  AgentRole,
  Attachment,
  Colleague,
  DiscussionMember,
  MemberToAdd,
  Message,
} from './api'

export const STREAMING_MESSAGE_ID = '__streaming__'
export const MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
export const POLLING_INTERVAL_MS = 5000

export interface MessageSessionState {
  channelId: string | null
  messages: Message[]
}

export type MessageSessionAction =
  | { type: 'channel_changed'; channelId: string | null }
  | { type: 'refresh_succeeded'; channelId: string; messages: Message[] }
  | { type: 'realtime_received'; message: Message }
  | {
    type: 'stream_started'
    channelId: string
    speakerAgentId: string | null
    speakerName: string
  }
  | { type: 'stream_delta'; channelId: string; text: string }
  | { type: 'stream_ended'; message: Message }
  | { type: 'stream_failed'; channelId: string }

export function messageSessionReducer(
  state: MessageSessionState,
  action: MessageSessionAction,
): MessageSessionState {
  switch (action.type) {
    case 'channel_changed':
      return { channelId: action.channelId, messages: [] }
    case 'refresh_succeeded': {
      if (action.channelId !== state.channelId) return state
      const remoteIds = new Set(action.messages.map((item) => item.id))
      const justArrived = state.messages.filter((item) => (
        item.channel_id === action.channelId && !remoteIds.has(item.id)
      ))
      return { ...state, messages: [...action.messages, ...justArrived] }
    }
    case 'realtime_received':
      if (
        action.message.channel_id !== state.channelId
        || state.messages.some((item) => item.id === action.message.id)
      ) return state
      return { ...state, messages: [...state.messages, action.message] }
    case 'stream_started':
      if (action.channelId !== state.channelId) return state
      return {
        ...state,
        messages: [...state.messages, {
          id: STREAMING_MESSAGE_ID,
          channel_id: action.channelId,
          speaker_type: 'ai',
          speaker_id: action.speakerAgentId,
          speaker_name: action.speakerName,
          content: '',
          mentioned_agent_ids: [],
          ai_source_record_id: null,
          ref_type: null,
          ref_id: null,
          create_time: '',
        }],
      }
    case 'stream_delta':
      if (action.channelId !== state.channelId) return state
      return {
        ...state,
        messages: state.messages.map((item) => (
          item.id === STREAMING_MESSAGE_ID
            ? { ...item, content: item.content + action.text }
            : item
        )),
      }
    case 'stream_ended': {
      if (action.message.channel_id !== state.channelId) return state
      const persistedAlreadyExists = state.messages.some((item) => item.id === action.message.id)
      const withoutStreaming = state.messages.filter((item) => item.id !== STREAMING_MESSAGE_ID)
      return {
        ...state,
        messages: persistedAlreadyExists
          ? withoutStreaming
          : [...withoutStreaming, action.message],
      }
    }
    case 'stream_failed':
      if (action.channelId !== state.channelId) return state
      return {
        ...state,
        messages: state.messages.filter((item) => item.id !== STREAMING_MESSAGE_ID),
      }
  }
}

interface BuildOutgoingMessageInput {
  members: DiscussionMember[]
  mentionIds: string[]
  text: string
  attachments: Attachment[]
}

export interface OutgoingMessage {
  content: string
  mentionedAgentIds: string[]
  attachments: Attachment[]
}

export function buildOutgoingMessage({
  members,
  mentionIds,
  text,
  attachments,
}: BuildOutgoingMessageInput): OutgoingMessage | null {
  const body = text.trim()
  if (!body && attachments.length === 0) return null

  const selected = members.filter((member) => mentionIds.includes(member.member_id))
  const prefix = selected
    .map((member) => `@${member.member_name || '成员'}`)
    .join(' ')
  const mentionedAgentIds = selected
    .filter((member) => member.member_type === 'ai')
    .map((member) => member.member_id)
    .slice(0, 3)

  return {
    content: [prefix, body].filter(Boolean).join(' ') || '[附件]',
    mentionedAgentIds,
    attachments,
  }
}

export function isAttachmentTooLarge(size: number): boolean {
  return size > MAX_ATTACHMENT_BYTES
}

export function isChannelOwner(member: DiscussionMember, ownerId: string | null): boolean {
  return member.member_type === 'human' && member.member_id === ownerId
}

export function canRemoveMember(
  member: DiscussionMember,
  currentUserIsOwner: boolean,
  ownerId: string | null,
): boolean {
  return currentUserIsOwner && !isChannelOwner(member, ownerId)
}

export function buildMembersToAdd(
  humanIds: string[],
  agentIds: string[],
  colleagues: Colleague[],
  agents: AgentRole[],
): MemberToAdd[] {
  return [
    ...humanIds.map((id) => {
      const colleague = colleagues.find((item) => item.id === id)
      return {
        member_type: 'human' as const,
        member_id: id,
        member_name: colleague?.real_name || colleague?.username,
      }
    }),
    ...agentIds.map((id) => ({
      member_type: 'ai' as const,
      member_id: id,
      member_name: agents.find((item) => item.id === id)?.name,
    })),
  ]
}

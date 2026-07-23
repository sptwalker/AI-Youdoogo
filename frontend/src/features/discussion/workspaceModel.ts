import type {
  AgentRole,
  ChannelWithUnread,
  Colleague,
  MemberToAdd,
} from './api'
import { buildMembersToAdd } from './model'

export type ActiveConversation =
  | { type: 'assistant' }
  | { type: 'group'; id: string; name: string }

export function channelSignature(channels: ChannelWithUnread[]): string {
  return channels.map((channel) => channel.id).sort().join(',')
}

export function incrementUnreadForIncoming(
  channels: ChannelWithUnread[],
  incomingChannelId: string,
  activeChannelId: string | null,
): ChannelWithUnread[] {
  if (incomingChannelId === activeChannelId) return channels
  const channelExists = channels.some((channel) => channel.id === incomingChannelId)
  if (!channelExists) return channels
  return channels.map((channel) => (
    channel.id === incomingChannelId
      ? { ...channel, unread: (channel.unread ?? 0) + 1 }
      : channel
  ))
}

export function reconcileActiveConversation(
  active: ActiveConversation,
  channels: ChannelWithUnread[],
): ActiveConversation {
  if (active.type === 'group' && !channels.some((channel) => channel.id === active.id)) {
    return { type: 'assistant' }
  }
  return active
}

interface BuildCreateDiscussionInput {
  name: string
  humanIds: string[]
  agentIds: string[]
  colleagues: Colleague[]
  agents: AgentRole[]
}

export function buildCreateDiscussionRequest({
  name,
  humanIds,
  agentIds,
  colleagues,
  agents,
}: BuildCreateDiscussionInput): { name: string; members: MemberToAdd[] } | null {
  const trimmedName = name.trim()
  if (!trimmedName) return null
  return {
    name: trimmedName,
    members: buildMembersToAdd(humanIds, agentIds, colleagues, agents),
  }
}

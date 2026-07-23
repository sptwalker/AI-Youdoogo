import { message } from 'antd'
import { useEffect, useState, type ComponentProps } from 'react'
import AssistantChatCard from '../../components/dashboard/AssistantChatCard'
import {
  discussionWorkspaceApi,
  type AgentRole,
  type Colleague,
  type MemberToAdd,
} from './api'
import { ConversationSidebar } from './components/ConversationSidebar'
import { NewDiscussionModal } from './components/NewDiscussionModal'
import GroupChat from './GroupChat'
import { useDiscussionFeed } from './hooks/useDiscussionFeed'
import { reconcileActiveConversation, type ActiveConversation } from './workspaceModel'

type AssistantChatProps = ComponentProps<typeof AssistantChatCard>

export interface DesktopConversationsProps {
  meId?: string
  assistant: AssistantChatProps
}

export default function DesktopConversations({
  meId,
  assistant,
}: DesktopConversationsProps) {
  const [active, setActive] = useState<ActiveConversation>({ type: 'assistant' })
  const [newGroupOpen, setNewGroupOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [agents, setAgents] = useState<AgentRole[]>([])
  const [colleagues, setColleagues] = useState<Colleague[]>([])
  const discussion = useDiscussionFeed({
    activeChannelId: active.type === 'group' ? active.id : null,
  })

  useEffect(() => {
    let disposed = false
    void discussionWorkspaceApi.listAgents()
      .then((items) => { if (!disposed) setAgents(items) })
      .catch(() => {})
    void discussionWorkspaceApi.listColleagues()
      .then((items) => { if (!disposed) setColleagues(items) })
      .catch(() => {})
    return () => { disposed = true }
  }, [])

  useEffect(() => {
    setActive((current) => reconcileActiveConversation(current, discussion.channels))
  }, [discussion.channels])

  const createDiscussion = async (request: { name: string; members: MemberToAdd[] }) => {
    setCreating(true)
    try {
      const channel = await discussionWorkspaceApi.createChannel(request)
      message.success('讨论组已创建')
      setNewGroupOpen(false)
      setActive({ type: 'group', id: channel.id, name: channel.name })
      try {
        await discussion.refreshChannels(true)
      } catch {
        discussion.restartRealtime()
      }
    } finally {
      setCreating(false)
    }
  }

  const activeChannel = active.type === 'group'
    ? discussion.channels.find((channel) => channel.id === active.id)
    : undefined

  return (
    <div style={{
      flex: 1,
      minHeight: 0,
      minWidth: 0,
      display: 'flex',
      gap: 12,
      marginTop: 16,
    }}>
      <ConversationSidebar
        channels={discussion.channels}
        active={active}
        onSelect={setActive}
        onCreate={() => setNewGroupOpen(true)}
      />

      <div style={{
        flex: 1,
        minHeight: 0,
        minWidth: 0,
        display: 'flex',
        flexDirection: 'column',
      }}>
        {active.type === 'group' ? (
          <GroupChat
            channelId={active.id}
            channelName={active.name}
            session={discussion.activeSession}
            isOwner={activeChannel?.creator_id === meId}
            ownerId={activeChannel?.creator_id ?? null}
            onMembershipChange={() => { void discussion.refreshChannels(true).catch(() => {}) }}
            onDisband={() => {
              setActive({ type: 'assistant' })
              void discussion.refreshChannels(true).catch(() => {})
            }}
          />
        ) : (
          <AssistantChatCard {...assistant} />
        )}
      </div>

      <NewDiscussionModal
        open={newGroupOpen}
        creating={creating}
        agents={agents}
        colleagues={colleagues}
        onClose={() => setNewGroupOpen(false)}
        onCreate={createDiscussion}
      />
    </div>
  )
}

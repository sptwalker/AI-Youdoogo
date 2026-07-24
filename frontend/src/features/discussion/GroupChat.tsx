import { message } from 'antd'
import { useCallback, useState } from 'react'
import { groupChatApi, type AgentRole, type MemberToAdd } from './api'
import { ChannelActions } from './components/ChannelActions'
import { MemberList } from './components/MemberList'
import { MemberPicker } from './components/MemberPicker'
import { MessageComposer } from './components/MessageComposer'
import { MessageList } from './components/MessageList'
import { useChannelMembers } from './hooks/useChannelMembers'
import type { ChannelMessageSession } from './hooks/useDiscussionFeed'
import { useMessageComposer } from './hooks/useMessageComposer'

export interface GroupChatProps {
  channelId: string
  channelName: string
  agents: AgentRole[]
  session: ChannelMessageSession
  isOwner: boolean
  ownerId: string | null
  onMembershipChange(): void
  onDisband(): void
}

export default function GroupChat({
  channelId,
  channelName,
  agents,
  session,
  isOwner,
  ownerId,
  onMembershipChange,
  onDisband,
}: GroupChatProps) {
  const [pickerOpen, setPickerOpen] = useState(false)
  const [membersOpen, setMembersOpen] = useState(false)
  const membership = useChannelMembers({ channelId, onMembershipChange })
  const notifyFileTooLarge = useCallback(() => { message.error('文件过大（>20MB）') }, [])
  const notifyUploadFailed = useCallback(() => { message.error('上传失败') }, [])
  const composer = useMessageComposer({
    channelId,
    members: membership.members,
    ingestStreamEvent: session.ingestStreamEvent,
    onFileTooLarge: notifyFileTooLarge,
    onUploadFailed: notifyUploadFailed,
  })

  const addMembers = async (selected: MemberToAdd[]) => {
    const added = await membership.addMembers(selected)
    if (!added) return
    message.success('已拉入')
    setPickerOpen(false)
  }

  const disband = async () => {
    await groupChatApi.disbandChannel(channelId)
    message.success('已解散')
    onDisband()
  }

  return (
    <div style={{
      flex: 1,
      minHeight: 0,
      minWidth: 0,
      display: 'flex',
      flexDirection: 'column',
    }}>
      <ChannelActions
        channelName={channelName}
        memberCount={membership.members.length}
        isOwner={isOwner}
        onOpenMembers={() => setMembersOpen(true)}
        onOpenPicker={() => setPickerOpen(true)}
        onDisband={disband}
      />
      <MessageList
        messages={session.messages}
        sending={composer.sending}
        onDownload={(attachment) => { void groupChatApi.downloadAttachment(attachment) }}
      />
      <MessageComposer members={membership.members} composer={composer} />
      <MemberPicker
        open={pickerOpen}
        existing={membership.memberIds}
        agents={agents}
        colleagues={membership.colleagues}
        onOpen={membership.loadColleagues}
        onClose={() => setPickerOpen(false)}
        onAdd={addMembers}
      />
      <MemberList
        open={membersOpen}
        members={membership.members}
        currentUserIsOwner={isOwner}
        ownerId={ownerId}
        onClose={() => setMembersOpen(false)}
        onRemove={async (member) => {
          await membership.removeMember(member)
          message.success('已踢出')
        }}
      />
    </div>
  )
}

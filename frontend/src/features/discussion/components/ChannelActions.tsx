import { Button, Popconfirm, Space, Tag } from 'antd'

interface ChannelActionsProps {
  channelName: string
  memberCount: number
  isOwner: boolean
  onOpenMembers(): void
  onOpenPicker(): void
  onDisband(): Promise<void>
}

export function ChannelActions({
  channelName,
  memberCount,
  isOwner,
  onOpenMembers,
  onOpenPicker,
  onDisband,
}: ChannelActionsProps) {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: 8,
    }}>
      <Space>
        <b>{channelName}</b>
        <a style={{ fontSize: 12 }} onClick={onOpenMembers}>{memberCount} 成员</a>
        {isOwner && <Tag color="gold">群主</Tag>}
      </Space>
      <Space>
        <Button size="small" onClick={onOpenPicker}>+ 拉人/AI</Button>
        {isOwner && (
          <Popconfirm
            title="解散该讨论群？聊天记录会存入知识库。"
            okText="解散"
            okButtonProps={{ danger: true }}
            onConfirm={onDisband}
          >
            <Button size="small" danger>解散群</Button>
          </Popconfirm>
        )}
      </Space>
    </div>
  )
}

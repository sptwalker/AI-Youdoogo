import { Badge, Card } from 'antd'
import type { ChannelWithUnread } from '../api'
import type { ActiveConversation } from '../workspaceModel'

interface ConversationSidebarProps {
  channels: ChannelWithUnread[]
  active: ActiveConversation
  onSelect(active: ActiveConversation): void
  onCreate(): void
}

export function ConversationSidebar({
  channels,
  active,
  onSelect,
  onCreate,
}: ConversationSidebarProps) {
  return (
    <Card
      size="small"
      title="对话"
      style={{ width: 152, flexShrink: 0, overflowY: 'auto' }}
      styles={{ body: { padding: 6 } }}
      extra={<a style={{ fontSize: 12 }} onClick={onCreate}>+群</a>}
    >
      <div
        onClick={() => onSelect({ type: 'assistant' })}
        style={{
          cursor: 'pointer',
          padding: '6px',
          borderRadius: 4,
          fontSize: 12,
          background: active.type === 'assistant' ? '#e6f4ff' : undefined,
        }}
      >
        💬 我的助理
      </div>
      {channels.map((channel) => {
        const selected = active.type === 'group' && active.id === channel.id
        return (
          <div
            key={channel.id}
            onClick={() => onSelect({ type: 'group', id: channel.id, name: channel.name })}
            style={{
              cursor: 'pointer',
              padding: '6px',
              borderRadius: 4,
              fontSize: 12,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              background: selected ? '#e6f4ff' : undefined,
            }}
          >
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              # {channel.name}
            </span>
            {channel.unread > 0 && !selected && <Badge count={channel.unread} size="small" />}
          </div>
        )
      })}
    </Card>
  )
}

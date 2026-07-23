import { Modal, Popconfirm, Space, Tag } from 'antd'
import type { DiscussionMember } from '../api'
import { canRemoveMember, isChannelOwner } from '../model'

interface MemberListProps {
  open: boolean
  members: DiscussionMember[]
  currentUserIsOwner: boolean
  ownerId: string | null
  onClose(): void
  onRemove(member: DiscussionMember): Promise<void>
}

export function MemberList({
  open,
  members,
  currentUserIsOwner,
  ownerId,
  onClose,
  onRemove,
}: MemberListProps) {
  return (
    <Modal open={open} onCancel={onClose} footer={null} title="群成员">
      {members.map((member) => {
        const owner = isChannelOwner(member, ownerId)
        return (
          <div
            key={`${member.member_type}-${member.member_id}`}
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '6px 0',
              borderTop: '1px solid #f0f0f0',
            }}
          >
            <Space>
              <span>{member.member_type === 'ai' ? '🤖' : '👤'}</span>
              <span>{member.member_name || '（未命名）'}</span>
              {owner && <Tag color="gold">群主</Tag>}
            </Space>
            {canRemoveMember(member, currentUserIsOwner, ownerId) && (
              <Popconfirm
                title={`把「${member.member_name || '该成员'}」踢出群？`}
                onConfirm={() => onRemove(member)}
              >
                <a style={{ color: '#cf1322' }}>踢出</a>
              </Popconfirm>
            )}
          </div>
        )
      })}
    </Modal>
  )
}

import { PaperClipOutlined } from '@ant-design/icons'
import { Button, Input, Select, Space, Tag, Upload } from 'antd'
import type { DiscussionMember } from '../api'
import type { MessageComposerState } from '../hooks/useMessageComposer'

interface MessageComposerProps {
  members: DiscussionMember[]
  composer: MessageComposerState
}

export function MessageComposer({ members, composer }: MessageComposerProps) {
  return (
    <>
      {composer.pendingAttachments.length > 0 && (
        <div style={{ marginBottom: 6, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {composer.pendingAttachments.map((attachment, index) => (
            <Tag key={index} closable onClose={() => composer.removeAttachment(index)}>
              <PaperClipOutlined /> {attachment.name}
            </Tag>
          ))}
        </div>
      )}
      <Space.Compact style={{ width: '100%' }}>
        <Select
          mode="multiple"
          allowClear
          style={{ minWidth: 150 }}
          placeholder="@成员（真人/AI）"
          value={composer.mentions}
          onChange={composer.setMentions}
          optionFilterProp="label"
          options={members.map((member) => ({
            value: member.member_id,
            label: `${member.member_type === 'ai' ? '🤖' : '👤'} ${member.member_name || '（未命名）'}`,
          }))}
        />
        <Upload beforeUpload={composer.upload} showUploadList={false} multiple>
          <Button
            icon={<PaperClipOutlined />}
            loading={composer.uploading}
            title="发图片/文件"
          />
        </Upload>
        <Input
          placeholder="发消息，回车发送"
          value={composer.text}
          onChange={(event) => composer.setText(event.target.value)}
          onPressEnter={() => { void composer.send() }}
        />
        <Button type="primary" loading={composer.sending} onClick={() => { void composer.send() }}>
          发送
        </Button>
      </Space.Compact>
    </>
  )
}

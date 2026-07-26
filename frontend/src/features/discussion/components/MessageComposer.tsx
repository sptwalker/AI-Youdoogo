import { CameraOutlined, PaperClipOutlined, SearchOutlined } from '@ant-design/icons'
import { Button, Input, Popover, Select, Tag, Typography, Upload, message } from 'antd'
import { useMemo, useState } from 'react'
import { EmojiStickerButton } from '../../chat/EmojiStickerButton'
import { captureScreenshot } from '../../chat/screenshot'
import type { DiscussionMember, Message } from '../api'
import type { MessageComposerState } from '../hooks/useMessageComposer'

interface MessageComposerProps {
  members: DiscussionMember[]
  composer: MessageComposerState
  messages: Message[]
}

export function MessageComposer({ members, composer, messages }: MessageComposerProps) {
  const [capturing, setCapturing] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')

  const searchResults = useMemo(() => {
    const term = searchTerm.trim().toLowerCase()
    if (!term) return []
    return messages.filter((item) => item.content.toLowerCase().includes(term))
  }, [messages, searchTerm])

  const handleScreenshot = async () => {
    setCapturing(true)
    try {
      const file = await captureScreenshot()
      if (file) await composer.upload(file)
    } catch (error) {
      // 用户取消选屏会 reject，静默；仅在浏览器不支持时提示
      if (error instanceof Error && error.message === 'unsupported') message.error('当前浏览器不支持截图')
    } finally {
      setCapturing(false)
    }
  }

  const jumpTo = (id: string) => {
    window.document.getElementById(`group-message-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    setSearchOpen(false)
  }

  const searchContent = (
    <div style={{ width: 280 }}>
      <Input
        autoFocus
        allowClear
        placeholder="搜索当前群聊"
        prefix={<SearchOutlined />}
        value={searchTerm}
        onChange={(event) => setSearchTerm(event.target.value)}
      />
      <div style={{ maxHeight: 260, overflowY: 'auto', marginTop: 8 }}>
        {searchTerm.trim() && searchResults.length === 0 && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>没有匹配的消息</Typography.Text>
        )}
        {searchResults.map((item) => (
          <div
            key={item.id}
            onClick={() => jumpTo(item.id)}
            style={{ cursor: 'pointer', padding: '6px 4px', borderBottom: '1px solid #f5f5f5', fontSize: 12 }}
          >
            <div style={{ color: '#888' }}>{item.speaker_name}</div>
            <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.content}</div>
          </div>
        ))}
      </div>
    </div>
  )

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
      <div style={{ border: '1px solid #e8e8e8', borderRadius: 8, background: '#fff', display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 2, padding: '2px 6px', borderBottom: '1px solid #f5f5f5' }}>
          <EmojiStickerButton
            variant="emoji"
            type="text"
            disabled={composer.sending}
            onInsertEmoji={(emoji) => composer.setText(composer.text + emoji)}
            onPickSticker={composer.upload}
          />
          <Button type="text" icon={<CameraOutlined />} loading={capturing} title="截图" onClick={() => void handleScreenshot()} />
          <EmojiStickerButton
            variant="sticker"
            type="text"
            disabled={composer.sending}
            onInsertEmoji={(emoji) => composer.setText(composer.text + emoji)}
            onPickSticker={composer.upload}
          />
          <Upload beforeUpload={composer.upload} showUploadList={false} multiple disabled={composer.sending}>
            <Button type="text" loading={composer.uploading} icon={<PaperClipOutlined />} title="附件" />
          </Upload>
          <Popover content={searchContent} trigger="click" open={searchOpen} onOpenChange={setSearchOpen} placement="topLeft">
            <Button type="text" icon={<SearchOutlined />} title="搜索聊天记录" />
          </Popover>
        </div>
        <Input.TextArea
          value={composer.text}
          onChange={(event) => composer.setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              void composer.send()
            }
          }}
          placeholder="发消息（Enter 发送，Shift+Enter 换行）"
          autoSize={{ minRows: 6, maxRows: 6 }}
          variant="borderless"
          disabled={composer.sending}
          style={{ resize: 'none', fontSize: 13 }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, padding: '4px 8px 8px' }}>
          <Select
            mode="multiple"
            allowClear
            style={{ flex: 1, minWidth: 0 }}
            placeholder="@成员（真人/AI）"
            value={composer.mentions}
            onChange={composer.setMentions}
            disabled={composer.sending}
            optionFilterProp="label"
            options={members.map((member) => ({
              value: member.member_id,
              label: `${member.member_type === 'ai' ? '🤖' : '👤'} ${member.member_name || '（未命名）'}`,
            }))}
          />
          <Button
            loading={composer.sending}
            disabled={composer.uploading}
            onClick={() => { void composer.send() }}
            style={{ minWidth: 88, background: '#d6e8ff', borderColor: '#b9d6ff', color: '#1677ff' }}
          >
            发送
          </Button>
        </div>
      </div>
    </>
  )
}

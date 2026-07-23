import { PaperClipOutlined } from '@ant-design/icons'
import { Spin, Tag, Typography } from 'antd'
import { useEffect, useRef } from 'react'
import Markdown from '../../../components/Markdown'
import { attachmentPreviewUrl, type Attachment, type Message } from '../api'

interface MessageListProps {
  messages: Message[]
  sending: boolean
  onDownload(attachment: Attachment): void
}

export function MessageList({ messages, sending, onDownload }: MessageListProps) {
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const element = boxRef.current
    if (element) element.scrollTop = element.scrollHeight
  }, [messages])

  return (
    <div
      ref={boxRef}
      style={{
        flex: 1,
        minHeight: 160,
        overflowY: 'auto',
        padding: '4px 2px',
        background: '#fafafa',
        borderRadius: 6,
        marginBottom: 10,
        fontSize: 12,
      }}
    >
      {messages.length === 0 && (
        <Typography.Text
          type="secondary"
          style={{ display: 'block', textAlign: 'center', marginTop: 80 }}
        >
          群里还没有消息。发一条，或 @AI 让它参与讨论。
        </Typography.Text>
      )}
      {messages.map((item) => (
        <MessageItem key={item.id} message={item} onDownload={onDownload} />
      ))}
      {sending && <div style={{ textAlign: 'center', margin: 8 }}><Spin size="small" /></div>}
    </div>
  )
}

function MessageItem({
  message,
  onDownload,
}: {
  message: Message
  onDownload(attachment: Attachment): void
}) {
  const isAi = message.speaker_type === 'ai'
  return (
    <div style={{ margin: '10px 6px' }}>
      <div style={{ fontSize: 12, color: '#888', marginBottom: 2 }}>
        {isAi && <Tag color="blue" style={{ marginRight: 4 }}>AI</Tag>}
        {message.speaker_name}
      </div>
      <span style={{
        display: 'inline-block',
        maxWidth: '82%',
        padding: '7px 11px',
        borderRadius: 8,
        background: '#fff',
        border: '1px solid #eee',
      }}>
        {isAi ? <Markdown>{message.content}</Markdown> : message.content}
      </span>
      {(message.attachments ?? []).map((attachment, index) => (
        <div key={index} style={{ marginTop: 4 }}>
          {attachment.type === 'image' ? (
            <img
              src={attachmentPreviewUrl(attachment)}
              alt={attachment.name}
              style={{
                maxWidth: 180,
                maxHeight: 180,
                borderRadius: 6,
                cursor: 'pointer',
              }}
              onClick={() => onDownload(attachment)}
            />
          ) : (
            <a onClick={() => onDownload(attachment)} style={{ fontSize: 12 }}>
              <PaperClipOutlined /> {attachment.name}
            </a>
          )}
        </div>
      ))}
    </div>
  )
}

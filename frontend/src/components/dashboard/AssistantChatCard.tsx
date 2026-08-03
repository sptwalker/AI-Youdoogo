import {
  CameraOutlined,
  CloseOutlined,
  MessageOutlined,
  PaperClipOutlined,
  PushpinOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import { Button, Card, Input, List, Popover, Select, Space, Spin, Tag, Typography, Upload, message } from 'antd'
import { useEffect, useMemo, useState, type CSSProperties, type Dispatch, type RefObject, type SetStateAction } from 'react'
import { fetchDesktopAttachment, type AddableAgent, type Attachment, type DesktopMessage } from '../../api/desktop'
import type { OrchProgress } from '../../api/tasks'
import { EmojiStickerButton } from '../../features/chat/EmojiStickerButton'
import { captureScreenshot } from '../../features/chat/screenshot'
import Markdown from '../Markdown'
import { formatExactTimestamp, formatSeparatorTime, parseMessageTime, shouldShowTimeSeparator, sortPinnedMessages } from './assistantChatModel'

type AssistantChatCardProps = {
  addable: AddableAgent[]
  addAgentIds: string[]
  assistant: { id: string; name: string } | null
  chatBoxRef: RefObject<HTMLDivElement | null>
  chatInput: string
  chatMessages: DesktopMessage[]
  chatSending: boolean
  chatUploading: boolean
  pendingAttachments: Attachment[]
  replyingTo: DesktopMessage | null
  orchestration: OrchProgress | null
  onAcceptStep: (stepId: string) => Promise<void>
  onCancelReply: () => void
  onDownloadAttachment: (attachment: Attachment) => Promise<void>
  onPinToggle: (message: DesktopMessage) => Promise<void>
  onRemoveAttachment: (index: number) => void
  onReply: (message: DesktopMessage) => void
  onSend: () => Promise<void>
  onUpload: (file: File) => Promise<boolean>
  setAddAgentIds: Dispatch<SetStateAction<string[]>>
  setChatInput: Dispatch<SetStateAction<string>>
  setOrchestration: Dispatch<SetStateAction<OrchProgress | null>>
}

const listStyle: CSSProperties = { flex: 1, minHeight: 200, overflowY: 'auto', padding: '4px 2px', background: '#fafafa', borderRadius: 6, marginBottom: 10, fontSize: 12 }
const timeStyle: CSSProperties = { textAlign: 'center', color: '#999', fontSize: 12, margin: '12px 0 6px' }
const imageStyle: CSSProperties = { maxWidth: 180, maxHeight: 180, borderRadius: 8, cursor: 'pointer', display: 'block' }

function scrollToMessage(messageId: string): void {
  window.document.getElementById(`desktop-message-${messageId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

function InlineImage({ attachment, canPreview, onDownload }: {
  attachment: Attachment
  canPreview: boolean
  onDownload: (attachment: Attachment) => Promise<void>
}) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  useEffect(() => {
    let disposed = false
    let objectUrl: string | null = null
    if (!canPreview) {
      setPreviewUrl(null)
      return () => {}
    }
    void fetchDesktopAttachment(attachment)
      .then((blob) => {
        if (disposed) return
        objectUrl = URL.createObjectURL(blob)
        setPreviewUrl(objectUrl)
      })
      .catch(() => { if (!disposed) setPreviewUrl(null) })
    return () => {
      disposed = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [attachment, canPreview])
  return previewUrl
    ? <img src={previewUrl} alt={attachment.name} style={imageStyle} onClick={() => void onDownload(attachment)} />
    : <a onClick={() => void onDownload(attachment)} style={{ fontSize: 12 }}><PaperClipOutlined /> {attachment.name}</a>
}

function MessageItem({ item, previous, hovered, onDownload, onHover, onPinToggle, onReply }: {
  item: DesktopMessage
  previous: DesktopMessage | null
  hovered: boolean
  onDownload: (attachment: Attachment) => Promise<void>
  onHover: (messageId: string | null) => void
  onPinToggle: (message: DesktopMessage) => Promise<void>
  onReply: (message: DesktopMessage) => void
}) {
  const mine = item.speaker_type === 'user'
  const messageTime = parseMessageTime(item.create_time)
  const bubbleStyle: CSSProperties = {
    display: 'inline-block', maxWidth: '82%', padding: '7px 11px', borderRadius: 8,
    textAlign: 'left', whiteSpace: mine ? 'pre-wrap' : 'normal',
    background: mine ? '#d6e8ff' : '#fff', border: mine ? '1px solid #b9d6ff' : '1px solid #eee',
  }
  return (
    <div id={`desktop-message-${item.id}`}>
      {shouldShowTimeSeparator(previous?.create_time, item.create_time) && messageTime && <div style={timeStyle}>{formatSeparatorTime(messageTime)}</div>}
      <div style={{ textAlign: mine ? 'right' : 'left', margin: '10px 6px' }} onMouseEnter={() => onHover(item.id)} onMouseLeave={() => onHover(null)}>
        <div style={{ fontSize: 12, color: '#888', marginBottom: 2, display: 'flex', justifyContent: mine ? 'flex-end' : 'flex-start', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          <span>{mine ? '我' : item.speaker_name}</span>
          {hovered && messageTime && <span style={{ color: '#b0b0b0' }}>{formatExactTimestamp(messageTime)}</span>}
          {hovered && item.create_time && <Space size={4}>
            <a onClick={() => onReply(item)}><MessageOutlined /> 引用</a>
            <a onClick={() => void onPinToggle(item)}><PushpinOutlined /> {item.is_pinned ? '取消置顶' : '置顶'}</a>
          </Space>}
        </div>
        <div style={bubbleStyle}>
          {item.reply_preview && <div style={{ marginBottom: 6, padding: '6px 8px', borderRadius: 6, background: mine ? '#c2ddff' : '#f5f5f5', borderLeft: `3px solid ${mine ? '#1677ff' : '#91caff'}`, fontSize: 12 }}>
            <div style={{ fontWeight: 600, marginBottom: 2 }}>{item.reply_preview.speaker_name}</div>
            <div style={{ opacity: mine ? 0.92 : 0.8 }}>{item.reply_preview.content}</div>
          </div>}
          {mine ? item.content : <Markdown>{item.content}</Markdown>}
          {item.attachments.length > 0 && <div style={{ marginTop: 8, display: 'grid', gap: 6 }}>{item.attachments.map((attachment, index) => (
            <div key={`${item.id}-${attachment.storage_path}-${index}`}>
              {attachment.type === 'image'
                ? <InlineImage attachment={attachment} canPreview={Boolean(item.create_time)} onDownload={onDownload} />
                : <a onClick={() => void onDownload(attachment)} style={{ fontSize: 12 }}><PaperClipOutlined /> {attachment.name}</a>}
            </div>
          ))}</div>}
        </div>
      </div>
    </div>
  )
}

function PinnedMessages({ messages, onPinToggle }: Pick<AssistantChatCardProps, 'onPinToggle'> & { messages: DesktopMessage[] }) {
  const pinnedMessages = useMemo(() => sortPinnedMessages(messages), [messages])
  if (pinnedMessages.length === 0) return null
  return <div style={{ marginBottom: 10, padding: '8px 10px', borderRadius: 8, background: '#fff7e6', border: '1px solid #ffe7ba', fontSize: 12 }}>
    <Space size={[6, 6]} wrap>
      <Tag color="gold"><PushpinOutlined /> 置顶</Tag>
      {pinnedMessages.map((message) => <Space key={message.id} size={4}>
        <a onClick={() => scrollToMessage(message.id)}>{message.speaker_name}：{(message.reply_preview?.content ?? message.content).slice(0, 24)}</a>
        <a title="取消置顶" onClick={() => void onPinToggle(message)}><CloseOutlined /></a>
      </Space>)}
    </Space>
  </div>
}

function ChatSearchButton({ messages }: { messages: DesktopMessage[] }) {
  const [open, setOpen] = useState(false)
  const [term, setTerm] = useState('')
  const results = useMemo(() => {
    const normalizedTerm = term.trim().toLowerCase()
    return normalizedTerm ? messages.filter((item) => item.content.toLowerCase().includes(normalizedTerm)) : []
  }, [messages, term])
  return <Popover trigger="click" open={open} onOpenChange={setOpen} placement="topLeft" content={<div style={{ width: 280 }}>
    <Input autoFocus allowClear placeholder="搜索当前对话" prefix={<SearchOutlined />} value={term} onChange={(event) => setTerm(event.target.value)} />
    <div style={{ maxHeight: 260, overflowY: 'auto', marginTop: 8 }}>
      {term.trim() && results.length === 0 && <Typography.Text type="secondary" style={{ fontSize: 12 }}>没有匹配的消息</Typography.Text>}
      {results.map((item) => <div key={item.id} onClick={() => { scrollToMessage(item.id); setOpen(false) }} style={{ cursor: 'pointer', padding: '6px 4px', borderBottom: '1px solid #f5f5f5', fontSize: 12 }}>
        <div style={{ color: '#888' }}>{item.speaker_name}</div>
        <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.content}</div>
      </div>)}
    </div>
  </div>}>
    <Button type="text" icon={<SearchOutlined />} title="搜索聊天记录" />
  </Popover>
}

export default function AssistantChatCard({
  addable, addAgentIds, assistant, chatBoxRef, chatInput, chatMessages, chatSending, chatUploading,
  pendingAttachments, replyingTo, orchestration, onAcceptStep, onCancelReply, onDownloadAttachment,
  onPinToggle, onRemoveAttachment, onReply, onSend, onUpload, setAddAgentIds, setChatInput, setOrchestration,
}: AssistantChatCardProps) {
  const [hoveredMessageId, setHoveredMessageId] = useState<string | null>(null)
  const [capturing, setCapturing] = useState(false)
  const handleScreenshot = async () => {
    setCapturing(true)
    try {
      const file = await captureScreenshot()
      if (file) await onUpload(file)
    } catch (error) {
      if (error instanceof Error && error.message === 'unsupported') message.error('当前浏览器不支持截图')
    } finally {
      setCapturing(false)
    }
  }
  const send = () => void onSend()
  return <Card
    title={assistant ? `与${assistant.name}对话` : '我的助理'}
    style={{ marginTop: 16, flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}
    styles={{ body: { flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' } }}
    extra={<Select mode="multiple" allowClear maxCount={2} style={{ minWidth: 220 }} placeholder="+ 加入AI圆桌（最多2个）" value={addAgentIds} onChange={setAddAgentIds} optionFilterProp="label" options={addable.map((agent) => ({ value: agent.id, label: agent.name }))} />}
  >
    <PinnedMessages messages={chatMessages} onPinToggle={onPinToggle} />
    <div ref={chatBoxRef} style={listStyle}>
      {chatMessages.length === 0 && <Typography.Text type="secondary" style={{ display: 'block', textAlign: 'center', marginTop: 120 }}>向你的助理提问，它会结合知识库与过往对话回答（仅供参考）。可加入其他 AI 一起圆桌讨论。</Typography.Text>}
      {chatMessages.map((item, index) => <MessageItem key={item.id} item={item} previous={index > 0 ? chatMessages[index - 1] : null} hovered={hoveredMessageId === item.id} onDownload={onDownloadAttachment} onHover={setHoveredMessageId} onPinToggle={onPinToggle} onReply={onReply} />)}
      {chatSending && <div style={{ textAlign: 'center', margin: 8 }}><Spin size="small" /></div>}
    </div>
    {orchestration && <Card size="small" style={{ marginBottom: 10, background: '#f6ffed' }} title={<span style={{ fontSize: 12 }}>任务进度 {orchestration.accepted}/{orchestration.total}{orchestration.done && <Tag color="green" style={{ marginLeft: 8 }}>已完成</Tag>}{orchestration.awaiting_human.length > 0 && <Tag color="orange" style={{ marginLeft: 8 }}>待验收</Tag>}</span>} extra={<a style={{ fontSize: 12 }} onClick={() => setOrchestration(null)}>收起</a>}>
      <List size="small" dataSource={orchestration.steps} renderItem={(step) => {
        const icon = step.status === 'accepted' ? '✅' : step.status === 'reported' ? '⏸' : step.status === 'executing' ? '▶' : '○'
        const waiting = step.red_line && step.status === 'reported'
        return <List.Item style={{ fontSize: 12, padding: '4px 0' }} actions={waiting ? [<a key="accept" onClick={() => void onAcceptStep(step.id)}>验收并继续</a>] : []}><Space size={6}><span>{icon}</span><span>步骤{step.step_no + 1}·{step.title}</span><Tag>{step.skill}</Tag>{step.red_line && <Tag color="red">红线</Tag>}</Space></List.Item>
      }} />
    </Card>}
    {replyingTo && <div style={{ marginBottom: 8, padding: '8px 10px', borderRadius: 8, background: '#f5f5f5', borderLeft: '3px solid #1677ff', fontSize: 12 }}><div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}><div style={{ minWidth: 0 }}><div style={{ color: '#1677ff', fontWeight: 600 }}>引用 {replyingTo.speaker_name}</div><div style={{ color: '#666', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{replyingTo.reply_preview?.content ?? replyingTo.content}</div></div><a onClick={onCancelReply}><CloseOutlined /></a></div></div>}
    {pendingAttachments.length > 0 && <div style={{ marginBottom: 8, display: 'grid', gap: 6 }}>{pendingAttachments.map((attachment, index) => <div key={`${attachment.storage_path}-${index}`} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 8px', borderRadius: 8, background: '#fafafa', border: '1px solid #f0f0f0', fontSize: 12 }}><Space size={6}><PaperClipOutlined /><span>{attachment.name}</span>{attachment.type === 'image' && <Tag color="blue">图片</Tag>}</Space><a onClick={() => onRemoveAttachment(index)}><CloseOutlined /></a></div>)}</div>}
    <div style={{ border: '1px solid #e8e8e8', borderRadius: 8, background: '#fff', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 2, padding: '2px 6px', borderBottom: '1px solid #f5f5f5' }}>
        <EmojiStickerButton variant="emoji" type="text" disabled={chatSending} onInsertEmoji={(emoji) => setChatInput((previous) => previous + emoji)} onPickSticker={onUpload} />
        <Button type="text" icon={<CameraOutlined />} loading={capturing} title="截图" onClick={() => void handleScreenshot()} />
        <EmojiStickerButton variant="sticker" type="text" disabled={chatSending} onInsertEmoji={(emoji) => setChatInput((previous) => previous + emoji)} onPickSticker={onUpload} />
        <Upload beforeUpload={onUpload} showUploadList={false} multiple><Button type="text" loading={chatUploading} icon={<PaperClipOutlined />} title="附件" /></Upload>
        <ChatSearchButton messages={chatMessages} />
      </div>
      <Input.TextArea value={chatInput} onChange={(event) => setChatInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send() } }} placeholder="向你的助理提问（Enter 发送，Shift+Enter 换行）" autoSize={{ minRows: 6, maxRows: 6 }} variant="borderless" style={{ resize: 'none', fontSize: 13 }} />
      <div style={{ display: 'flex', justifyContent: 'flex-end', padding: '4px 8px 8px' }}><Button loading={chatSending} onClick={send} style={{ minWidth: 88, background: '#d6e8ff', borderColor: '#b9d6ff', color: '#1677ff' }}>发送</Button></div>
    </div>
  </Card>
}

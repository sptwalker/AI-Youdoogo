import { CameraOutlined, CloseOutlined, MessageOutlined, PaperClipOutlined, PushpinOutlined, SearchOutlined } from '@ant-design/icons'
import { Button, Card, Input, List, Popover, Select, Space, Spin, Tag, Typography, Upload, message } from 'antd'
import { useEffect, useMemo, useState, type Dispatch, type RefObject, type SetStateAction } from 'react'
import {
  fetchDesktopAttachment,
  type AddableAgent,
  type Attachment,
  type DesktopMessage,
} from '../../api/desktop'
import type { OrchProgress } from '../../api/tasks'
import { EmojiStickerButton } from '../../features/chat/EmojiStickerButton'
import { captureScreenshot } from '../../features/chat/screenshot'
import Markdown from '../Markdown'

const TIME_SEPARATOR_GAP_MS = 3 * 60 * 1000

export function parseMessageTime(createTime: string): Date | null {
  if (!createTime) return null
  const parsed = new Date(createTime)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

export function shouldShowTimeSeparator(previousCreateTime: string | null | undefined, currentCreateTime: string): boolean {
  const currentTime = parseMessageTime(currentCreateTime)
  if (!currentTime) return false
  if (previousCreateTime == null) return true
  if (!previousCreateTime) return false
  const previousTime = parseMessageTime(previousCreateTime)
  if (!previousTime) return false
  return currentTime.getTime() - previousTime.getTime() > TIME_SEPARATOR_GAP_MS
}

export function sortPinnedMessages(messages: DesktopMessage[]): DesktopMessage[] {
  return messages
    .filter((message) => message.is_pinned)
    .sort((left, right) => (right.pinned_at ?? '').localeCompare(left.pinned_at ?? ''))
}

function formatSeparatorTime(messageTime: Date): string {
  return messageTime.toLocaleString([], {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatExactTimestamp(messageTime: Date): string {
  return messageTime.toLocaleString()
}

function InlineImage(props: {
  attachment: Attachment
  canPreview: boolean
  onDownload: (attachment: Attachment) => Promise<void>
}) {
  const { attachment, canPreview, onDownload } = props
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
      .catch(() => {
        if (!disposed) setPreviewUrl(null)
      })
    return () => {
      disposed = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [attachment, canPreview])

  if (!previewUrl) {
    return (
      <a onClick={() => void onDownload(attachment)} style={{ fontSize: 12 }}>
        <PaperClipOutlined /> {attachment.name}
      </a>
    )
  }

  return (
    <img
      src={previewUrl}
      alt={attachment.name}
      style={{
        maxWidth: 180,
        maxHeight: 180,
        borderRadius: 8,
        cursor: 'pointer',
        display: 'block',
      }}
      onClick={() => void onDownload(attachment)}
    />
  )
}

export default function AssistantChatCard(props: {
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
}) {
  const {
    addable,
    addAgentIds,
    assistant,
    chatBoxRef,
    chatInput,
    chatMessages,
    chatSending,
    chatUploading,
    pendingAttachments,
    replyingTo,
    orchestration,
    onAcceptStep,
    onCancelReply,
    onDownloadAttachment,
    onPinToggle,
    onRemoveAttachment,
    onReply,
    onSend,
    onUpload,
    setAddAgentIds,
    setChatInput,
    setOrchestration,
  } = props
  const [hoveredMessageId, setHoveredMessageId] = useState<string | null>(null)
  const [capturing, setCapturing] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const pinnedMessages = useMemo(() => sortPinnedMessages(chatMessages), [chatMessages])
  const searchResults = useMemo(() => {
    const term = searchTerm.trim().toLowerCase()
    if (!term) return []
    return chatMessages.filter((item) => item.content.toLowerCase().includes(term))
  }, [chatMessages, searchTerm])

  const scrollToMessage = (messageId: string) => {
    window.document.getElementById(`desktop-message-${messageId}`)?.scrollIntoView({
      behavior: 'smooth',
      block: 'center',
    })
  }

  const handleScreenshot = async () => {
    setCapturing(true)
    try {
      const file = await captureScreenshot()
      if (file) await onUpload(file)
    } catch (error) {
      // 用户取消选屏会 reject，静默；仅在浏览器不支持时提示
      if (error instanceof Error && error.message === 'unsupported') message.error('当前浏览器不支持截图')
    } finally {
      setCapturing(false)
    }
  }

  const searchContent = (
    <div style={{ width: 280 }}>
      <Input
        autoFocus
        allowClear
        placeholder="搜索当前对话"
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
            onClick={() => { scrollToMessage(item.id); setSearchOpen(false) }}
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
    <Card
      title={assistant ? `与${assistant.name}对话` : '我的助理'}
      style={{ marginTop: 16, flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}
      styles={{ body: { flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' } }}
      extra={
        <Select
          mode="multiple"
          allowClear
          maxCount={2}
          style={{ minWidth: 220 }}
          placeholder="+ 加入AI圆桌（最多2个）"
          value={addAgentIds}
          onChange={setAddAgentIds}
          optionFilterProp="label"
          options={addable.map((agent) => ({ value: agent.id, label: agent.name }))}
        />
      }
    >
      {pinnedMessages.length > 0 && (
        <div style={{
          marginBottom: 10,
          padding: '8px 10px',
          borderRadius: 8,
          background: '#fff7e6',
          border: '1px solid #ffe7ba',
          fontSize: 12,
        }}>
          <Space size={[6, 6]} wrap>
            <Tag color="gold"><PushpinOutlined /> 置顶</Tag>
            {pinnedMessages.map((message) => (
              <Space key={message.id} size={4}>
                <a onClick={() => scrollToMessage(message.id)}>
                  {message.speaker_name}：{(message.reply_preview?.content ?? message.content).slice(0, 24)}
                </a>
                <a title="取消置顶" onClick={() => void onPinToggle(message)}><CloseOutlined /></a>
              </Space>
            ))}
          </Space>
        </div>
      )}

      <div
        ref={chatBoxRef}
        style={{ flex: 1, minHeight: 200, overflowY: 'auto', padding: '4px 2px', background: '#fafafa', borderRadius: 6, marginBottom: 10, fontSize: 12 }}
      >
        {chatMessages.length === 0 && (
          <Typography.Text type="secondary" style={{ display: 'block', textAlign: 'center', marginTop: 120 }}>
            向你的助理提问，它会结合知识库与过往对话回答（仅供参考）。可加入其他 AI 一起圆桌讨论。
          </Typography.Text>
        )}
        {chatMessages.map((chatMessage, index) => {
          const mine = chatMessage.speaker_type === 'user'
          const headerName = mine ? '我' : chatMessage.speaker_name
          const previousMessage = index > 0 ? chatMessages[index - 1] : null
          const messageTime = parseMessageTime(chatMessage.create_time)
          const showTimeSeparator = shouldShowTimeSeparator(previousMessage?.create_time, chatMessage.create_time)
          const exactTimestampText = hoveredMessageId === chatMessage.id && messageTime
            ? formatExactTimestamp(messageTime)
            : null
          const canInteract = Boolean(chatMessage.create_time)
          return (
            <div key={chatMessage.id} id={`desktop-message-${chatMessage.id}`}>
              {showTimeSeparator && messageTime && (
                <div style={{ textAlign: 'center', color: '#999', fontSize: 12, margin: '12px 0 6px' }}>
                  {formatSeparatorTime(messageTime)}
                </div>
              )}
              <div
                style={{ textAlign: mine ? 'right' : 'left', margin: '10px 6px' }}
                onMouseEnter={() => setHoveredMessageId(chatMessage.id)}
                onMouseLeave={() => setHoveredMessageId((current) => (current === chatMessage.id ? null : current))}
              >
                <div style={{
                  fontSize: 12,
                  color: '#888',
                  marginBottom: 2,
                  display: 'flex',
                  justifyContent: mine ? 'flex-end' : 'flex-start',
                  alignItems: 'center',
                  gap: 6,
                  flexWrap: 'wrap',
                }}>
                  <span>{headerName}</span>
                  {exactTimestampText && <span style={{ color: '#b0b0b0' }}>{exactTimestampText}</span>}
                  {hoveredMessageId === chatMessage.id && canInteract && (
                    <Space size={4}>
                      <a onClick={() => onReply(chatMessage)}><MessageOutlined /> 引用</a>
                      <a onClick={() => void onPinToggle(chatMessage)}>
                        <PushpinOutlined /> {chatMessage.is_pinned ? '取消置顶' : '置顶'}
                      </a>
                    </Space>
                  )}
                </div>
                <div
                  style={{
                    display: 'inline-block',
                    maxWidth: '82%',
                    padding: '7px 11px',
                    borderRadius: 8,
                    textAlign: 'left',
                    whiteSpace: mine ? 'pre-wrap' : 'normal',
                    background: mine ? '#d6e8ff' : '#fff',
                    border: mine ? '1px solid #b9d6ff' : '1px solid #eee',
                  }}
                >
                  {chatMessage.reply_preview && (
                    <div style={{
                      marginBottom: 6,
                      padding: '6px 8px',
                      borderRadius: 6,
                      background: mine ? '#c2ddff' : '#f5f5f5',
                      borderLeft: `3px solid ${mine ? '#1677ff' : '#91caff'}`,
                      fontSize: 12,
                    }}>
                      <div style={{ fontWeight: 600, marginBottom: 2 }}>{chatMessage.reply_preview.speaker_name}</div>
                      <div style={{ opacity: mine ? 0.92 : 0.8 }}>{chatMessage.reply_preview.content}</div>
                    </div>
                  )}
                  {mine ? chatMessage.content : <Markdown>{chatMessage.content}</Markdown>}
                  {chatMessage.attachments.length > 0 && (
                    <div style={{ marginTop: 8, display: 'grid', gap: 6 }}>
                      {chatMessage.attachments.map((attachment, attachmentIndex) => (
                        <div key={`${chatMessage.id}-${attachment.storage_path}-${attachmentIndex}`}>
                          {attachment.type === 'image' ? (
                            <InlineImage
                              attachment={attachment}
                              canPreview={Boolean(chatMessage.create_time)}
                              onDownload={onDownloadAttachment}
                            />
                          ) : (
                            <a onClick={() => void onDownloadAttachment(attachment)} style={{ fontSize: 12 }}>
                              <PaperClipOutlined /> {attachment.name}
                            </a>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )
        })}
        {chatSending && <div style={{ textAlign: 'center', margin: 8 }}><Spin size="small" /></div>}
      </div>

      {orchestration && (
        <Card
          size="small"
          style={{ marginBottom: 10, background: '#f6ffed' }}
          title={
            <span style={{ fontSize: 12 }}>
              任务进度 {orchestration.accepted}/{orchestration.total}
              {orchestration.done && <Tag color="green" style={{ marginLeft: 8 }}>已完成</Tag>}
              {orchestration.awaiting_human.length > 0 && <Tag color="orange" style={{ marginLeft: 8 }}>待验收</Tag>}
            </span>
          }
          extra={<a style={{ fontSize: 12 }} onClick={() => setOrchestration(null)}>收起</a>}
        >
          <List
            size="small"
            dataSource={orchestration.steps}
            renderItem={(step) => {
              const icon = step.status === 'accepted' ? '✅' : step.status === 'reported' ? '⏸' : step.status === 'executing' ? '▶' : '○'
              const waiting = step.red_line && step.status === 'reported'
              return (
                <List.Item
                  style={{ fontSize: 12, padding: '4px 0' }}
                  actions={waiting ? [<a key="ac" onClick={() => void onAcceptStep(step.id)}>验收并继续</a>] : []}
                >
                  <Space size={6}>
                    <span>{icon}</span>
                    <span>步骤{step.step_no + 1}·{step.title}</span>
                    <Tag>{step.skill}</Tag>
                    {step.red_line && <Tag color="red">红线</Tag>}
                  </Space>
                </List.Item>
              )
            }}
          />
        </Card>
      )}

      {replyingTo && (
        <div style={{
          marginBottom: 8,
          padding: '8px 10px',
          borderRadius: 8,
          background: '#f5f5f5',
          borderLeft: '3px solid #1677ff',
          fontSize: 12,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ color: '#1677ff', fontWeight: 600 }}>引用 {replyingTo.speaker_name}</div>
              <div style={{ color: '#666', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {(replyingTo.reply_preview?.content ?? replyingTo.content)}
              </div>
            </div>
            <a onClick={onCancelReply}><CloseOutlined /></a>
          </div>
        </div>
      )}

      {pendingAttachments.length > 0 && (
        <div style={{ marginBottom: 8, display: 'grid', gap: 6 }}>
          {pendingAttachments.map((attachment, index) => (
            <div key={`${attachment.storage_path}-${index}`} style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '6px 8px',
              borderRadius: 8,
              background: '#fafafa',
              border: '1px solid #f0f0f0',
              fontSize: 12,
            }}>
              <Space size={6}>
                <PaperClipOutlined />
                <span>{attachment.name}</span>
                {attachment.type === 'image' && <Tag color="blue">图片</Tag>}
              </Space>
              <a onClick={() => onRemoveAttachment(index)}><CloseOutlined /></a>
            </div>
          ))}
        </div>
      )}

      <div style={{ border: '1px solid #e8e8e8', borderRadius: 8, background: '#fff', display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 2, padding: '2px 6px', borderBottom: '1px solid #f5f5f5' }}>
          <EmojiStickerButton
            variant="emoji"
            type="text"
            disabled={chatSending}
            onInsertEmoji={(emoji) => setChatInput((prev) => prev + emoji)}
            onPickSticker={onUpload}
          />
          <Button type="text" icon={<CameraOutlined />} loading={capturing} title="截图" onClick={() => void handleScreenshot()} />
          <EmojiStickerButton
            variant="sticker"
            type="text"
            disabled={chatSending}
            onInsertEmoji={(emoji) => setChatInput((prev) => prev + emoji)}
            onPickSticker={onUpload}
          />
          <Upload beforeUpload={onUpload} showUploadList={false} multiple>
            <Button type="text" loading={chatUploading} icon={<PaperClipOutlined />} title="附件" />
          </Upload>
          <Popover content={searchContent} trigger="click" open={searchOpen} onOpenChange={setSearchOpen} placement="topLeft">
            <Button type="text" icon={<SearchOutlined />} title="搜索聊天记录" />
          </Popover>
        </div>
        <Input.TextArea
          value={chatInput}
          onChange={(event) => setChatInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              void onSend()
            }
          }}
          placeholder="向你的助理提问（Enter 发送，Shift+Enter 换行）"
          autoSize={{ minRows: 6, maxRows: 6 }}
          variant="borderless"
          style={{ resize: 'none', fontSize: 13 }}
        />
        <div style={{ display: 'flex', justifyContent: 'flex-end', padding: '4px 8px 8px' }}>
          <Button loading={chatSending} onClick={() => void onSend()} style={{ minWidth: 88, background: '#d6e8ff', borderColor: '#b9d6ff', color: '#1677ff' }}>发送</Button>
        </div>
      </div>
    </Card>
  )
}

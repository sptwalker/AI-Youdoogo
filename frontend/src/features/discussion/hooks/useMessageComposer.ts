import { useCallback, useEffect, useRef, useState } from 'react'
import { groupChatApi, type Attachment, type DiscussionMember, type GroupChatApi } from '../api'
import { buildOutgoingMessage, isAttachmentTooLarge } from '../model'

interface UseMessageComposerOptions {
  channelId: string
  members: DiscussionMember[]
  ingestStreamEvent(event: string, data: Record<string, unknown>): void
  clearStreamingMessage(): void
  onFileTooLarge(): void
  onUploadFailed(): void
  api?: GroupChatApi
}

export interface MessageComposerState {
  text: string
  mentions: string[]
  pendingAttachments: Attachment[]
  sending: boolean
  uploading: boolean
  setText(value: string): void
  setMentions(value: string[]): void
  removeAttachment(index: number): void
  upload(file: File): Promise<boolean>
  send(): Promise<void>
}

export function useMessageComposer({
  channelId,
  members,
  ingestStreamEvent,
  clearStreamingMessage,
  onFileTooLarge,
  onUploadFailed,
  api = groupChatApi,
}: UseMessageComposerOptions): MessageComposerState {
  const [text, setText] = useState('')
  const [mentions, setMentions] = useState<string[]>([])
  const [pendingAttachments, setPendingAttachments] = useState<Attachment[]>([])
  const [sending, setSending] = useState(false)
  const [uploadCount, setUploadCount] = useState(0)
  const sendingRef = useRef(false)
  const uploadCountRef = useRef(0)
  const activeRequestRef = useRef<AbortController | null>(null)

  useEffect(() => () => activeRequestRef.current?.abort(), [])

  const removeAttachment = useCallback((index: number) => {
    setPendingAttachments((current) => current.filter((_, itemIndex) => itemIndex !== index))
  }, [])

  const upload = useCallback(async (file: File): Promise<boolean> => {
    if (isAttachmentTooLarge(file.size)) {
      onFileTooLarge()
      return false
    }
    uploadCountRef.current += 1
    setUploadCount(uploadCountRef.current)
    try {
      const attachment = await api.uploadAttachment(file)
      setPendingAttachments((current) => [...current, attachment])
    } catch {
      onUploadFailed()
    } finally {
      uploadCountRef.current = Math.max(0, uploadCountRef.current - 1)
      setUploadCount(uploadCountRef.current)
    }
    return false
  }, [api, onFileTooLarge, onUploadFailed])

  const send = useCallback(async () => {
    const outgoing = buildOutgoingMessage({
      members,
      mentionIds: mentions,
      text,
      attachments: pendingAttachments,
    })
    if (!outgoing || sendingRef.current || uploadCountRef.current > 0) return

    const controller = new AbortController()
    activeRequestRef.current = controller
    sendingRef.current = true
    setSending(true)
    try {
      await api.postMessage(
        channelId,
        outgoing.content,
        outgoing.mentionedAgentIds,
        ingestStreamEvent,
        outgoing.attachments,
        { signal: controller.signal },
      )
      setText('')
      setPendingAttachments([])
      setMentions([])
    } catch {
      clearStreamingMessage()
    } finally {
      if (activeRequestRef.current === controller) activeRequestRef.current = null
      sendingRef.current = false
      setSending(false)
    }
  }, [api, channelId, clearStreamingMessage, ingestStreamEvent, members, mentions, pendingAttachments, text])

  return {
    text,
    mentions,
    pendingAttachments,
    sending,
    uploading: uploadCount > 0,
    setText,
    setMentions,
    removeAttachment,
    upload,
    send,
  }
}

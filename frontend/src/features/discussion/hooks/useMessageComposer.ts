import { useCallback, useRef, useState } from 'react'
import { groupChatApi, type Attachment, type DiscussionMember, type GroupChatApi } from '../api'
import { buildOutgoingMessage, isAttachmentTooLarge } from '../model'
import { useStreamingSend } from './useStreamingSend'

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
  const [uploadCount, setUploadCount] = useState(0)
  const uploadCountRef = useRef(0)
  const { sending, sendingRef, submit } = useStreamingSend(clearStreamingMessage)

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

    await submit(async (signal) => {
      await api.postMessage(
        channelId,
        outgoing.content,
        outgoing.mentionedAgentIds,
        ingestStreamEvent,
        outgoing.attachments,
        { signal },
      )
      setText('')
      setPendingAttachments([])
      setMentions([])
    })
  }, [api, channelId, ingestStreamEvent, members, mentions, pendingAttachments, sendingRef, submit, text])

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

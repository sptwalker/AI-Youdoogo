import { useCallback, useRef, useState } from 'react'
import { groupChatApi, type Attachment, type DiscussionMember, type GroupChatApi } from '../api'
import { buildOutgoingMessage, isAttachmentTooLarge } from '../model'

interface UseMessageComposerOptions {
  channelId: string
  members: DiscussionMember[]
  ingestStreamEvent(event: string, data: Record<string, unknown>): void
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
  onFileTooLarge,
  onUploadFailed,
  api = groupChatApi,
}: UseMessageComposerOptions): MessageComposerState {
  const [text, setText] = useState('')
  const [mentions, setMentions] = useState<string[]>([])
  const [pendingAttachments, setPendingAttachments] = useState<Attachment[]>([])
  const [sending, setSending] = useState(false)
  const [uploading, setUploading] = useState(false)
  const sendingRef = useRef(false)

  const removeAttachment = useCallback((index: number) => {
    setPendingAttachments((current) => current.filter((_, itemIndex) => itemIndex !== index))
  }, [])

  const upload = useCallback(async (file: File): Promise<boolean> => {
    if (isAttachmentTooLarge(file.size)) {
      onFileTooLarge()
      return false
    }
    setUploading(true)
    try {
      const attachment = await api.uploadAttachment(file)
      setPendingAttachments((current) => [...current, attachment])
    } catch {
      onUploadFailed()
    } finally {
      setUploading(false)
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
    if (!outgoing || sendingRef.current) return

    setText('')
    setPendingAttachments([])
    setMentions([])
    sendingRef.current = true
    setSending(true)
    try {
      await api.postMessage(
        channelId,
        outgoing.content,
        outgoing.mentionedAgentIds,
        ingestStreamEvent,
        outgoing.attachments,
      )
    } catch {
      // The shared SSE client already reports transport errors to the user.
    } finally {
      sendingRef.current = false
      setSending(false)
    }
  }, [api, channelId, ingestStreamEvent, members, mentions, pendingAttachments, text])

  return {
    text,
    mentions,
    pendingAttachments,
    sending,
    uploading,
    setText,
    setMentions,
    removeAttachment,
    upload,
    send,
  }
}

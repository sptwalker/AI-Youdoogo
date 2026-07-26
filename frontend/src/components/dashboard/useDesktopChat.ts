/** 桌面助理对话状态拥有者：拉取历史、附件上传、乐观发送、流式回写与失败恢复。 */
import { message } from 'antd'
import { useCallback, useEffect, useRef, useState, type Dispatch, type RefObject, type SetStateAction } from 'react'
import { parseStreamEvent } from '../../api/client'
import {
  downloadDesktopAttachment,
  getDesktopChat,
  pinDesktopMessage,
  sendDesktopChat,
  unpinDesktopMessage,
  uploadDesktopAttachment,
  type AddableAgent,
  type Attachment,
  type DesktopMessage,
} from '../../api/desktop'
import type { OrchProgress } from '../../api/tasks'
import { buildOutgoingMessage, isAttachmentTooLarge } from '../../features/discussion/model'
import {
  DESKTOP_STREAMING_MESSAGE_PREFIX,
  appendDesktopAiDelta,
  beginDesktopAiTurn,
  buildReplyPreview,
  clearFailedDesktopChat,
  mergeDesktopChatMessages,
  reconcileDesktopStreamMessageEnd,
} from './desktopChatModel'

interface UseDesktopChatOptions {
  onAfterSend?(): void | Promise<unknown>
}

export interface DesktopChatState {
  assistant: { id: string; name: string } | null
  addable: AddableAgent[]
  addAgentIds: string[]
  chatBoxRef: RefObject<HTMLDivElement | null>
  chatInput: string
  chatMessages: DesktopMessage[]
  chatSending: boolean
  chatUploading: boolean
  pendingAttachments: Attachment[]
  replyingTo: DesktopMessage | null
  orchestration: OrchProgress | null
  onCancelReply(): void
  onDownloadAttachment(attachment: Attachment): Promise<void>
  onPinToggle(messageRow: DesktopMessage): Promise<void>
  onRemoveAttachment(index: number): void
  onReply(messageRow: DesktopMessage): void
  onSend(): Promise<void>
  onUpload(file: File): Promise<boolean>
  setAddAgentIds: Dispatch<SetStateAction<string[]>>
  setChatInput: Dispatch<SetStateAction<string>>
  setOrchestration: Dispatch<SetStateAction<OrchProgress | null>>
}

export function useDesktopChat({ onAfterSend }: UseDesktopChatOptions = {}): DesktopChatState {
  const [assistant, setAssistant] = useState<{ id: string; name: string } | null>(null)
  const [addable, setAddable] = useState<AddableAgent[]>([])
  const [addAgentIds, setAddAgentIds] = useState<string[]>([])
  const [chatMessages, setChatMessages] = useState<DesktopMessage[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatSending, setChatSending] = useState(false)
  const [chatUploading, setChatUploading] = useState(false)
  const [pendingAttachments, setPendingAttachments] = useState<Attachment[]>([])
  const [replyingTo, setReplyingTo] = useState<DesktopMessage | null>(null)
  const [orchestration, setOrchestration] = useState<OrchProgress | null>(null)
  const chatBoxRef = useRef<HTMLDivElement>(null)
  const activeAiTurnIdRef = useRef<string | null>(null)
  const aiTurnSequenceRef = useRef(0)
  const chatRequestRef = useRef<AbortController | null>(null)
  const chatSendingRef = useRef(false)

  useEffect(() => () => chatRequestRef.current?.abort(), [])

  useEffect(() => {
    const element = chatBoxRef.current
    if (element) element.scrollTop = element.scrollHeight
  }, [chatMessages])

  useEffect(() => {
    let disposed = false
    void getDesktopChat().then((chat) => {
      if (disposed) return
      setAssistant(chat.assistant)
      setChatMessages((items) => mergeDesktopChatMessages(chat.messages, items))
      setAddable(chat.addable_agents)
    })
    return () => { disposed = true }
  }, [])

  const uploadChatAttachment = useCallback(async (file: File): Promise<boolean> => {
    if (isAttachmentTooLarge(file.size)) {
      message.error('文件过大（>20MB）')
      return false
    }
    setChatUploading(true)
    try {
      const attachment = await uploadDesktopAttachment(file)
      setPendingAttachments((items) => [...items, attachment])
    } catch {
      // request() 已统一提示
    } finally {
      setChatUploading(false)
    }
    return false
  }, [])

  const togglePin = useCallback(async (messageRow: DesktopMessage) => {
    const updated = messageRow.is_pinned
      ? await unpinDesktopMessage(messageRow.id)
      : await pinDesktopMessage(messageRow.id)
    setChatMessages((items) => items.map((item) => (item.id === updated.id ? updated : item)))
  }, [])

  const sendChat = useCallback(async () => {
    if (chatSendingRef.current) return
    const draftInput = chatInput
    const draftAttachments = pendingAttachments
    const outgoing = buildOutgoingMessage({
      members: [],
      mentionIds: [],
      text: draftInput,
      attachments: draftAttachments,
    })
    if (!outgoing) {
      message.warning('请先输入文字或附带图片、文件')
      return
    }

    const optimisticId = `tmp-${Date.now()}`
    const draftReply = replyingTo
    const controller = new AbortController()
    const optimisticMessage: DesktopMessage = {
      id: optimisticId,
      speaker_type: 'user',
      speaker_agent_id: null,
      speaker_name: '我',
      content: outgoing.content,
      create_time: '',
      reply_to_message_id: draftReply?.id ?? null,
      reply_preview: draftReply ? buildReplyPreview(draftReply) : null,
      attachments: draftAttachments,
      is_pinned: false,
      pinned_at: null,
      pinned_by_user_id: null,
    }

    chatRequestRef.current = controller
    chatSendingRef.current = true
    activeAiTurnIdRef.current = null
    setChatInput('')
    setPendingAttachments([])
    setReplyingTo(null)
    setChatSending(true)
    setChatMessages((items) => [...items, optimisticMessage])
    try {
      await sendDesktopChat(
        {
          message: outgoing.content,
          addAgentIds,
          replyToMessageId: draftReply?.id,
          attachments: outgoing.attachments,
        },
        (event, payload) => {
          const parsed = parseStreamEvent<DesktopMessage, OrchProgress>(event, payload)
          if (parsed?.type === 'message_start') {
            const previousTurnId = activeAiTurnIdRef.current
            const turnId = `${DESKTOP_STREAMING_MESSAGE_PREFIX}${++aiTurnSequenceRef.current}`
            activeAiTurnIdRef.current = turnId
            setChatMessages((items) => beginDesktopAiTurn(items, previousTurnId, turnId, parsed.payload))
          } else if (parsed?.type === 'delta') {
            const activeTurnId = activeAiTurnIdRef.current
            setChatMessages((items) => appendDesktopAiDelta(items, activeTurnId, parsed.payload.text))
          } else if (parsed?.type === 'message_end') {
            const activeTurnId = activeAiTurnIdRef.current
            setChatMessages((items) => reconcileDesktopStreamMessageEnd(
              items,
              parsed.payload,
              optimisticId,
              activeTurnId,
            ))
            if (parsed.payload.speaker_type === 'ai') activeAiTurnIdRef.current = null
          } else if (parsed?.type === 'orchestration') {
            setOrchestration(parsed.payload)
          }
        },
        { signal: controller.signal },
      )
    } catch {
      setChatMessages((items) => clearFailedDesktopChat(items, optimisticId))
      setChatInput(draftInput)
      setPendingAttachments(draftAttachments)
      setReplyingTo(draftReply)
    } finally {
      if (chatRequestRef.current === controller) chatRequestRef.current = null
      chatSendingRef.current = false
      activeAiTurnIdRef.current = null
      setChatSending(false)
      if (onAfterSend) void Promise.resolve(onAfterSend()).catch(() => {})
    }
  }, [addAgentIds, chatInput, onAfterSend, pendingAttachments, replyingTo])

  return {
    assistant,
    addable,
    addAgentIds,
    chatBoxRef,
    chatInput,
    chatMessages,
    chatSending,
    chatUploading,
    pendingAttachments,
    replyingTo,
    orchestration,
    onCancelReply: () => setReplyingTo(null),
    onDownloadAttachment: downloadDesktopAttachment,
    onPinToggle: togglePin,
    onRemoveAttachment: (index) => setPendingAttachments((items) => items.filter((_, itemIndex) => itemIndex !== index)),
    onReply: setReplyingTo,
    onSend: sendChat,
    onUpload: uploadChatAttachment,
    setAddAgentIds,
    setChatInput,
    setOrchestration,
  }
}

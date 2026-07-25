/** 真人工作桌面路由容器：数据编排、动作处理和独立展示区组装。 */
import { ModalForm, PageContainer, ProFormSelect, ProFormTextArea } from '@ant-design/pro-components'
import { Col, Popconfirm, Row, Select, message } from 'antd'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import type { UserInfo } from '../api/auth'
import { reviewCollab } from '../api/collab'
import {
  downloadDeliverable,
  downloadDesktopAttachment,
  getDesktopChat,
  pinDesktopMessage,
  sendDesktopChat,
  unpinDesktopMessage,
  uploadDesktopAttachment,
  type AddableAgent,
  type Attachment,
  type DesktopMessage,
  type PendingItem,
} from '../api/desktop'
import { confirmResolution } from '../api/meetings'
import { reviewProposal } from '../api/proposals'
import { getOrchestrationProgress, transitionTask, type OrchProgress } from '../api/tasks'
import { buildOutgoingMessage, isAttachmentTooLarge } from '../features/discussion/model'
import DashboardSidebar from '../components/dashboard/DashboardSidebar'
import DesktopConversations from '../components/dashboard/DesktopConversations'
import PendingCard from '../components/dashboard/PendingCard'
import {
  DESKTOP_STREAMING_MESSAGE_PREFIX,
  appendDesktopAiDelta,
  beginDesktopAiTurn,
  clearFailedDesktopChat,
  reconcileDesktopMessageEnd as reconcileDesktopStreamMessageEnd,
} from '../components/dashboard/desktopChatModel'
import { useDashboardData } from '../hooks/useDashboardData'
import { usePendingActions } from '../hooks/usePendingActions'

const STREAMING_MESSAGE_ID = '__streaming__'
const MAX_REPLY_PREVIEW_CHARS = 120

function upsertDesktopMessage(items: DesktopMessage[], persisted: DesktopMessage): DesktopMessage[] {
  const persistedIndex = items.findIndex((item) => item.id === persisted.id)
  if (persistedIndex < 0) return [...items, persisted]
  return items.map((item, index) => (index === persistedIndex ? persisted : item))
}

export function startDesktopStreamingMessage(
  items: DesktopMessage[],
  start: { speaker_agent_id: string | null; speaker_name: string },
): DesktopMessage[] {
  return [
    ...items.filter((item) => item.id !== STREAMING_MESSAGE_ID),
    {
      id: STREAMING_MESSAGE_ID,
      speaker_type: 'ai',
      speaker_agent_id: start.speaker_agent_id,
      speaker_name: start.speaker_name,
      content: '',
      create_time: '',
      reply_to_message_id: null,
      reply_preview: null,
      attachments: [],
      is_pinned: false,
      pinned_at: null,
      pinned_by_user_id: null,
    },
  ]
}

export function reconcileDesktopMessageEnd(
  items: DesktopMessage[],
  persisted: DesktopMessage,
  optimisticId: string,
): DesktopMessage[] {
  const placeholderId = persisted.speaker_type === 'user' ? optimisticId : STREAMING_MESSAGE_ID
  const withoutPlaceholder = items.filter((item) => item.id !== placeholderId)
  return upsertDesktopMessage(withoutPlaceholder, persisted)
}

function buildReplyPreview(messageRow: DesktopMessage): DesktopMessage['reply_preview'] {
  const compact = messageRow.content.split(/\s+/).filter(Boolean).join(' ')
  return {
    id: messageRow.id,
    speaker_name: messageRow.speaker_name,
    content: compact.length <= MAX_REPLY_PREVIEW_CHARS
      ? compact
      : `${compact.slice(0, MAX_REPLY_PREVIEW_CHARS - 1)}…`,
  }
}

export function mergeDesktopChatMessages(
  fetched: DesktopMessage[],
  current: DesktopMessage[],
): DesktopMessage[] {
  if (current.length === 0) return fetched
  let merged = [...fetched]
  for (const item of current) {
    if (item.id === STREAMING_MESSAGE_ID || item.id.startsWith('tmp-')) {
      if (!merged.some((message) => message.id === item.id)) merged = [...merged, item]
      continue
    }
    merged = upsertDesktopMessage(merged, item)
  }
  return merged
}

export default function Dashboard() {
  const { me } = useOutletContext<{ me: UserInfo | null }>()
  const navigate = useNavigate()
  const { data, deliverables, loadDeliverables, reload, setViewUser, users, viewUser } = useDashboardData(me)
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
  const actionState = usePendingActions()

  useEffect(() => () => chatRequestRef.current?.abort(), [])

  useEffect(() => {
    const element = chatBoxRef.current
    if (element) element.scrollTop = element.scrollHeight
  }, [chatMessages])

  useEffect(() => {
    void getDesktopChat().then((chat) => {
      setAssistant(chat.assistant)
      setChatMessages((items) => mergeDesktopChatMessages(chat.messages, items))
      setAddable(chat.addable_agents)
    })
  }, [])

  const act = async (key: string, action: () => Promise<unknown>, success: string) => {
    return actionState.run(key, async () => {
      await action()
      message.success(success)
      await reload()
      return true
    })
  }

  const uploadChatAttachment = async (file: File): Promise<boolean> => {
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
  }

  const togglePin = async (messageRow: DesktopMessage) => {
    const updated = messageRow.is_pinned
      ? await unpinDesktopMessage(messageRow.id)
      : await pinDesktopMessage(messageRow.id)
    setChatMessages((items) => items.map((item) => (item.id === updated.id ? updated : item)))
  }

  const sendChat = async () => {
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

    const query = outgoing.content
    const optimisticId = `tmp-${Date.now()}`
    const draftReply = replyingTo
    const controller = new AbortController()
    const optimisticMessage: DesktopMessage = {
      id: optimisticId,
      speaker_type: 'user',
      speaker_agent_id: null,
      speaker_name: '我',
      content: query,
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
          message: query,
          addAgentIds,
          replyToMessageId: draftReply?.id,
          attachments: draftAttachments,
        },
        (event, payload) => {
          if (event === 'message_start') {
            const start = payload as { speaker_agent_id: string | null; speaker_name: string }
            const previousTurnId = activeAiTurnIdRef.current
            const turnId = `${DESKTOP_STREAMING_MESSAGE_PREFIX}${++aiTurnSequenceRef.current}`
            activeAiTurnIdRef.current = turnId
            setChatMessages((items) => beginDesktopAiTurn(items, previousTurnId, turnId, start))
          } else if (event === 'delta') {
            const text = String((payload as { text?: unknown }).text ?? '')
            const activeTurnId = activeAiTurnIdRef.current
            setChatMessages((items) => appendDesktopAiDelta(items, activeTurnId, text))
          } else if (event === 'message_end') {
            const persisted = payload as DesktopMessage
            const activeTurnId = activeAiTurnIdRef.current
            setChatMessages((items) => reconcileDesktopStreamMessageEnd(
              items,
              persisted,
              optimisticId,
              activeTurnId,
            ))
            if (persisted.speaker_type === 'ai') activeAiTurnIdRef.current = null
          } else if (event === 'orchestration') {
            setOrchestration(payload as OrchProgress)
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
      void loadDeliverables()
    }
  }

  const acceptStep = async (stepId: string) => {
    if (!orchestration) return
    const parentId = orchestration.parent_id
    await actionState.run(`orchestration:${stepId}`, async () => {
      await transitionTask(stepId, 'accepted')
      message.success('已验收，继续推进')
      setOrchestration(await getOrchestrationProgress(parentId))
      await reload()
    })
  }

  const pendingActions = (pending: PendingItem): ReactNode[] => {
    if (pending.kind === 'task') return [
      <Popconfirm key="a" title="验收此任务？" onConfirm={() => act(`task:${pending.id}:accepted`, () => transitionTask(pending.id, 'accepted'), '已验收')}><a>验收</a></Popconfirm>,
      <Popconfirm key="r" title="驳回此任务？" onConfirm={() => act(`task:${pending.id}:rejected`, () => transitionTask(pending.id, 'rejected'), '已驳回')}><a style={{ color: '#cf1322' }}>驳回</a></Popconfirm>,
    ]
    if (pending.kind === 'proposal') return [
      <ModalForm<{ decision: 'approve' | 'reject'; conclusion: string }>
        key="rv"
        title={`评审提案 ${pending.meta ?? ''}`}
        trigger={<a>评审</a>}
        modalProps={{ destroyOnHidden: true }}
        onFinish={async (value) => Boolean(await act(`proposal:${pending.id}:review`, () => reviewProposal(pending.id, value.decision, value.conclusion), '已评审'))}
      >
        <ProFormSelect name="decision" label="决定" initialValue="approve" rules={[{ required: true }]} options={[{ value: 'approve', label: '通过' }, { value: 'reject', label: '驳回' }]} />
        <ProFormTextArea name="conclusion" label="评审意见" rules={[{ required: true }]} />
      </ModalForm>,
    ]
    if (pending.kind === 'resolution') return [
      <Popconfirm key="c" title="确认此决议生效？（红线动作）" onConfirm={() => act(`resolution:${pending.id}:confirm`, () => confirmResolution(pending.id), '决议已确认')}><a>确认生效</a></Popconfirm>,
    ]
    return [
      <Popconfirm key="a" title="复核通过此协作请求？" onConfirm={() => act(`collab:${pending.id}:approve`, () => reviewCollab(pending.id, 'approve'), '已通过')}><a>通过</a></Popconfirm>,
      <Popconfirm key="r" title="驳回此协作请求？" onConfirm={() => act(`collab:${pending.id}:reject`, () => reviewCollab(pending.id, 'reject'), '已驳回')}><a style={{ color: '#cf1322' }}>驳回</a></Popconfirm>,
    ]
  }

  const isSupervising = Boolean(viewUser && viewUser !== me?.id)
  return (
    <PageContainer
      title="工作桌面"
      subTitle={isSupervising ? `监督：${data?.user.name ?? ''}` : '待我处理 · 与 AI 对话 · 我的任务'}
      extra={me?.role_code === 'admin' ? [
        <Select key="sup" allowClear placeholder="监督查看某员工桌面" style={{ width: 220 }} value={viewUser} onChange={setViewUser} options={users.map((user) => ({ value: user.id, label: user.real_name || user.username }))} />,
      ] : undefined}
    >
      <Row gutter={16} style={{ overflow: 'hidden' }}>
        <Col xs={24} lg={15}>
          <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 130px)', minHeight: 480 }}>
            <PendingCard data={data} actions={pendingActions} />
            {!isSupervising && (
              <DesktopConversations
                meId={me?.id}
                assistant={{
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
                  onAcceptStep: acceptStep,
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
                }}
              />
            )}
          </div>
        </Col>
        <Col xs={24} lg={9}>
          <DashboardSidebar
            data={data}
            deliverables={deliverables}
            isSupervising={isSupervising}
            onDownload={downloadDeliverable}
            onNavigate={navigate}
            onRefreshDeliverables={loadDeliverables}
          />
        </Col>
      </Row>
    </PageContainer>
  )
}

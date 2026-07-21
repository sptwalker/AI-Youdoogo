/** 真人工作桌面路由容器：数据编排、动作处理和独立展示区组装。 */
import { ModalForm, PageContainer, ProFormSelect, ProFormTextArea } from '@ant-design/pro-components'
import { Col, Popconfirm, Row, Select, message } from 'antd'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import type { UserInfo } from '../api/auth'
import { reviewCollab } from '../api/collab'
import { downloadDeliverable, getDesktopChat, sendDesktopChat, type AddableAgent, type DesktopMessage, type PendingItem } from '../api/desktop'
import { confirmResolution } from '../api/meetings'
import { reviewProposal } from '../api/proposals'
import { getOrchestrationProgress, transitionTask, type OrchProgress } from '../api/tasks'
import DashboardSidebar from '../components/dashboard/DashboardSidebar'
import DesktopConversations from '../components/dashboard/DesktopConversations'
import PendingCard from '../components/dashboard/PendingCard'
import { useDashboardData } from '../hooks/useDashboardData'

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
  const [orchestration, setOrchestration] = useState<OrchProgress | null>(null)
  const chatBoxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const element = chatBoxRef.current
    if (element) element.scrollTop = element.scrollHeight
  }, [chatMessages])

  useEffect(() => {
    void getDesktopChat().then((chat) => {
      setAssistant(chat.assistant)
      setChatMessages(chat.messages)
      setAddable(chat.addable_agents)
    })
  }, [])

  const act = async (action: () => Promise<unknown>, success: string) => {
    await action()
    message.success(success)
    await reload()
  }

  const sendChat = async () => {
    if (!chatInput.trim() || chatSending) return
    const query = chatInput.trim()
    const optimisticId = `tmp-${Date.now()}`
    const streamId = '__streaming__'
    setChatInput('')
    setChatSending(true)
    setChatMessages((items) => [...items, { id: optimisticId, speaker_type: 'user', speaker_agent_id: null, speaker_name: '我', content: query, create_time: '' }])
    try {
      await sendDesktopChat(query, addAgentIds, (event, payload) => {
        if (event === 'message_start') {
          const start = payload as unknown as { speaker_agent_id: string | null; speaker_name: string }
          setChatMessages((items) => [...items, { id: streamId, speaker_type: 'ai', speaker_agent_id: start.speaker_agent_id, speaker_name: start.speaker_name, content: '', create_time: '' }])
        } else if (event === 'delta') {
          const text = String((payload as { text?: unknown }).text ?? '')
          setChatMessages((items) => items.map((item) => item.id === streamId ? { ...item, content: item.content + text } : item))
        } else if (event === 'message_end') {
          const persisted = payload as unknown as DesktopMessage
          const replaceId = persisted.speaker_type === 'user' ? optimisticId : streamId
          setChatMessages((items) => items.map((item) => item.id === replaceId ? persisted : item))
        } else if (event === 'orchestration') {
          setOrchestration(payload as unknown as OrchProgress)
        }
      })
    } catch {
      setChatMessages((items) => items.filter((item) => item.id !== streamId && item.id !== optimisticId))
      setChatInput(query)
    } finally {
      setChatSending(false)
      void loadDeliverables()
    }
  }

  const acceptStep = async (stepId: string) => {
    if (!orchestration) return
    await transitionTask(stepId, 'accepted')
    message.success('已验收，继续推进')
    setOrchestration(await getOrchestrationProgress(orchestration.parent_id))
    await reload()
  }

  const pendingActions = (pending: PendingItem): ReactNode[] => {
    if (pending.kind === 'task') return [
      <Popconfirm key="a" title="验收此任务？" onConfirm={() => act(() => transitionTask(pending.id, 'accepted'), '已验收')}><a>验收</a></Popconfirm>,
      <Popconfirm key="r" title="驳回此任务？" onConfirm={() => act(() => transitionTask(pending.id, 'rejected'), '已驳回')}><a style={{ color: '#cf1322' }}>驳回</a></Popconfirm>,
    ]
    if (pending.kind === 'proposal') return [
      <ModalForm<{ decision: 'approve' | 'reject'; conclusion: string }>
        key="rv"
        title={`评审提案 ${pending.meta ?? ''}`}
        trigger={<a>评审</a>}
        modalProps={{ destroyOnHidden: true }}
        onFinish={async (value) => { await act(() => reviewProposal(pending.id, value.decision, value.conclusion), '已评审'); return true }}
      >
        <ProFormSelect name="decision" label="决定" initialValue="approve" rules={[{ required: true }]} options={[{ value: 'approve', label: '通过' }, { value: 'reject', label: '驳回' }]} />
        <ProFormTextArea name="conclusion" label="评审意见" rules={[{ required: true }]} />
      </ModalForm>,
    ]
    if (pending.kind === 'resolution') return [
      <Popconfirm key="c" title="确认此决议生效？（红线动作）" onConfirm={() => act(() => confirmResolution(pending.id), '决议已确认')}><a>确认生效</a></Popconfirm>,
    ]
    return [
      <Popconfirm key="a" title="复核通过此协作请求？" onConfirm={() => act(() => reviewCollab(pending.id, 'approve'), '已通过')}><a>通过</a></Popconfirm>,
      <Popconfirm key="r" title="驳回此协作请求？" onConfirm={() => act(() => reviewCollab(pending.id, 'reject'), '已驳回')}><a style={{ color: '#cf1322' }}>驳回</a></Popconfirm>,
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
                  orchestration,
                  onAcceptStep: acceptStep,
                  onSend: sendChat,
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

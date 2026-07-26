/** 真人工作桌面路由容器：数据编排、动作处理和独立展示区组装。 */
import { ModalForm, PageContainer, ProFormSelect, ProFormTextArea } from '@ant-design/pro-components'
import { Popconfirm, Select, Splitter, message } from 'antd'
import { type ReactNode } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import type { UserInfo } from '../api/auth'
import { reviewCollab } from '../api/collab'
import { downloadDeliverable, type PendingItem } from '../api/desktop'
import { confirmResolution } from '../api/meetings'
import { reviewProposal } from '../api/proposals'
import { getOrchestrationProgress, transitionTask } from '../api/tasks'
import DashboardSidebar from '../components/dashboard/DashboardSidebar'
import DesktopConversations from '../components/dashboard/DesktopConversations'
import PendingCard from '../components/dashboard/PendingCard'
import { useDesktopChat } from '../components/dashboard/useDesktopChat'
import { useDashboardData } from '../hooks/useDashboardData'
import { usePendingActions } from '../hooks/usePendingActions'

/** 工作桌面左右分栏宽度的本地存储：存左栏百分比，跨会话记住用户拖出的布局。 */
const SPLIT_KEY = 'youdoo_desktop_split'

function readSplit(): string {
  return localStorage.getItem(SPLIT_KEY) ?? '62%'
}

function saveSplit(sizes: number[]): void {
  const total = sizes[0] + sizes[1]
  if (total > 0) localStorage.setItem(SPLIT_KEY, `${Math.round((sizes[0] / total) * 100)}%`)
}

export default function Dashboard() {
  const { me } = useOutletContext<{ me: UserInfo | null }>()
  const navigate = useNavigate()
  const { data, deliverables, loadDeliverables, reload, setViewUser, users, viewUser } = useDashboardData(me)
  const actionState = usePendingActions()
  const desktopChat = useDesktopChat({ onAfterSend: loadDeliverables })

  const act = async (key: string, action: () => Promise<unknown>, success: string) => {
    return actionState.run(key, async () => {
      await action()
      message.success(success)
      await reload()
      return true
    })
  }

  const acceptStep = async (stepId: string) => {
    if (!desktopChat.orchestration) return
    const parentId = desktopChat.orchestration.parent_id
    await actionState.run(`orchestration:${stepId}`, async () => {
      await transitionTask(stepId, 'accepted')
      message.success('已验收，继续推进')
      desktopChat.setOrchestration(await getOrchestrationProgress(parentId))
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
      <Splitter style={{ height: 'calc(100vh - 130px)', minHeight: 480 }} onResizeEnd={saveSplit}>
        <Splitter.Panel defaultSize={readSplit()} min="35%">
          <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, overflow: 'hidden', paddingRight: 8 }}>
            <PendingCard data={data} actions={pendingActions} />
            {!isSupervising && (
              <DesktopConversations
                meId={me?.id}
                assistant={{
                  ...desktopChat,
                  onAcceptStep: acceptStep,
                }}
              />
            )}
          </div>
        </Splitter.Panel>
        <Splitter.Panel min="20%">
          <div style={{ height: '100%', paddingLeft: 8 }}>
            <DashboardSidebar
              data={data}
              deliverables={deliverables}
              isSupervising={isSupervising}
              onDownload={downloadDeliverable}
              onNavigate={navigate}
              onRefreshDeliverables={loadDeliverables}
            />
          </div>
        </Splitter.Panel>
      </Splitter>
    </PageContainer>
  )
}

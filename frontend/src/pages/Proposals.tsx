/** 提案：创建 / AI预研 / 真人评审(通过·驳回) / 转任务卡（红线：真人确认后落地）。 */
import {
  ModalForm,
  PageContainer,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components'
import { Button, Modal, Tag, Typography, message } from 'antd'
import { useRef, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import type { UserInfo } from '../api/auth'
import Markdown from '../components/Markdown'
import {
  aiResearch,
  convertProposal,
  createProposal,
  getProposal,
  listProposals,
  PROPOSAL_STATUS,
  reviewProposal,
  type Proposal,
  type Review,
} from '../api/proposals'
import { hasManagerRole } from './managementPermissions'
import { canResearchProposal } from '../features/proposals/model'
import { usePendingActions } from '../hooks/usePendingActions'

const STATUS_COLOR: Record<string, string> = {
  draft: 'default',
  researching: 'processing',
  reviewed: 'gold',
  approved: 'success',
  rejected: 'error',
}

export default function Proposals() {
  const { me } = useOutletContext<{ me: UserInfo | null }>()
  const actionRef = useRef<ActionType>(null)
  const [reviews, setReviews] = useState<Review[] | null>(null)
  const detailRequestRef = useRef(0)
  const pending = usePendingActions()
  const canManage = hasManagerRole(me?.role_code)
  const reload = () => actionRef.current?.reload()

  const openDetail = async (id: string) => {
    const requestId = ++detailRequestRef.current
    const { reviews } = await getProposal(id)
    if (requestId === detailRequestRef.current) setReviews(reviews)
  }

  const columns: ProColumns<Proposal>[] = [
    { title: '编号', dataIndex: 'code', copyable: true, search: false },
    { title: '标题', dataIndex: 'title' },
    {
      title: '状态',
      dataIndex: 'status',
      valueEnum: Object.fromEntries(
        Object.entries(PROPOSAL_STATUS).map(([k, v]) => [k, { text: v }]),
      ),
      render: (_, r) => (
        <Tag color={STATUS_COLOR[r.status] ?? 'default'}>
          {PROPOSAL_STATUS[r.status] ?? r.status}
        </Tag>
      ),
    },
    { title: '优先级', dataIndex: 'priority', search: false },
    { title: '创建时间', dataIndex: 'create_time', valueType: 'dateTime', search: false },
    {
      title: '操作',
      valueType: 'option',
      render: (_, r) => {
        const a = [<a key="d" onClick={() => openDetail(r.id)}>详情</a>]
        if (canManage && canResearchProposal(r.status)) {
          const researchKey = `research:${r.id}`
          a.push(
            <Button
              key="ai"
              type="link"
              size="small"
              loading={pending.isPending(researchKey)}
              onClick={() => {
                void pending.run(researchKey, async () => {
                  message.loading({ content: 'AI 预研中…', key: researchKey, duration: 0 })
                  try {
                    await aiResearch(r.id)
                    message.success({ content: '预研完成', key: researchKey })
                    reload()
                  } catch (error) {
                    message.destroy(researchKey)
                    throw error
                  }
                }).catch(() => {})
              }}
            >AI预研</Button>,
          )
        }
        if (canManage && r.status === 'reviewed') {
          a.push(
            <ModalForm<{ decision: 'approve' | 'reject'; conclusion: string }>
              key="rv"
              title="真人评审"
              trigger={<a>评审</a>}
              modalProps={{ destroyOnHidden: true }}
              onFinish={async (v) => {
                await reviewProposal(r.id, v.decision, v.conclusion)
                message.success('已评审')
                reload()
                return true
              }}
            >
              <ProFormSelect name="decision" label="决定" initialValue="approve" options={[
                { value: 'approve', label: '通过' }, { value: 'reject', label: '驳回' }]} rules={[{ required: true }]} />
              <ProFormTextArea name="conclusion" label="评审意见" rules={[{ required: true }]} />
            </ModalForm>,
          )
        }
        if (canManage && r.status === 'approved' && !r.converted_task_id) {
          a.push(
            <Button
              key="cv"
              type="link"
              size="small"
              loading={pending.isPending(`convert:${r.id}`)}
              onClick={() => {
                void pending.run(`convert:${r.id}`, async () => {
                  await convertProposal(r.id)
                  message.success('已转任务卡')
                  reload()
                }).catch(() => {})
              }}
            >转任务卡</Button>,
          )
        }
        return a
      },
    },
  ]

  return (
    <PageContainer title="提案">
      <ProTable<Proposal>
        rowKey="id"
        actionRef={actionRef}
        columns={columns}
        request={async (p) => ({ data: await listProposals(p.status as string | undefined), success: true })}
        toolBarRender={() => [
          <ModalForm<{ title: string; background: string; plan: string; benefit_risk?: string; priority: string }>
            key="new"
            title="新建提案"
            trigger={<Button type="primary">新建提案</Button>}
            modalProps={{ destroyOnHidden: true }}
            onFinish={async (v) => {
              await createProposal(v)
              message.success('已创建')
              reload()
              return true
            }}
          >
            <ProFormText name="title" label="标题" rules={[{ required: true }]} />
            <ProFormTextArea name="background" label="背景与问题" rules={[{ required: true }]} />
            <ProFormTextArea name="plan" label="方案" rules={[{ required: true }]} />
            <ProFormTextArea name="benefit_risk" label="收益与风险" />
            <ProFormSelect name="priority" label="优先级" initialValue="normal" options={[
              { value: 'high', label: '高' }, { value: 'normal', label: '普通' }, { value: 'low', label: '低' }]} />
          </ModalForm>,
        ]}
      />
      <Modal open={reviews !== null} onCancel={() => { detailRequestRef.current += 1; setReviews(null) }} footer={null} title="评审记录" width={640}>
        {(reviews || []).map((rv) => (
          <div key={rv.id} style={{ marginBottom: 12 }}>
            <Tag color={rv.review_type === 'ai_research' ? 'blue' : 'green'}>
              {rv.review_type === 'ai_research' ? 'AI预研' : `真人评审 · ${rv.decision}`}
            </Tag>
            <Typography.Paragraph style={{ marginTop: 4 }}>
              <Markdown>{rv.conclusion}</Markdown>
            </Typography.Paragraph>
          </div>
        ))}
        {reviews?.length === 0 && '暂无评审记录'}
      </Modal>
    </PageContainer>
  )
}

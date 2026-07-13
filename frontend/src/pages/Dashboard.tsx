/** 真人工作桌面（F5a）：真人员工的统一工作枢纽。
 *  待我处理（验收/评审/确认/复核 合并同性质）+ 我的任务 + 发起 + 对话/资料入口 + admin 监督。
 *  红线：桌面只发起/处理，生效动作仍走各自真人确认端点。 */
import { ModalForm, PageContainer, ProFormSelect, ProFormTextArea } from '@ant-design/pro-components'
import { Badge, Button, Card, Col, Empty, List, Popconfirm, Row, Select, Space, Tag, Typography, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { listUsers, type UserInfo } from '../api/auth'
import { reviewCollab } from '../api/collab'
import { getDesktop, type Desktop, type PendingItem } from '../api/desktop'
import { confirmResolution } from '../api/meetings'
import { reviewProposal } from '../api/proposals'
import { STATUS_LABEL, transitionTask } from '../api/tasks'

const KIND: Record<PendingItem['kind'], { label: string; color: string }> = {
  task: { label: '待验收', color: 'blue' },
  proposal: { label: '待评审', color: 'gold' },
  resolution: { label: '待确认', color: 'purple' },
  collab: { label: '待复核', color: 'volcano' },
}
const PRIORITY_COLOR: Record<string, string> = { high: 'red', normal: 'default', low: 'default' }

export default function Dashboard() {
  const { me } = useOutletContext<{ me: UserInfo | null }>()
  const nav = useNavigate()
  const [data, setData] = useState<Desktop | null>(null)
  const [viewUser, setViewUser] = useState<string | undefined>()
  const [users, setUsers] = useState<UserInfo[]>([])

  const reload = useCallback(async () => setData(await getDesktop(viewUser)), [viewUser])
  useEffect(() => {
    void reload()
  }, [reload])
  useEffect(() => {
    if (me?.role_code === 'admin') void listUsers().then(setUsers)
  }, [me])

  const act = async (fn: () => Promise<unknown>, okMsg: string) => {
    await fn()
    message.success(okMsg)
    await reload()
  }

  /** 一条待办按类型渲染 inline 操作。 */
  const actions = (p: PendingItem) => {
    if (p.kind === 'task')
      return [
        <Popconfirm key="a" title="验收此任务？" onConfirm={() => act(() => transitionTask(p.id, 'accepted'), '已验收')}>
          <a>验收</a>
        </Popconfirm>,
        <Popconfirm key="r" title="驳回此任务？" onConfirm={() => act(() => transitionTask(p.id, 'rejected'), '已驳回')}>
          <a style={{ color: '#cf1322' }}>驳回</a>
        </Popconfirm>,
      ]
    if (p.kind === 'proposal')
      return [
        <ModalForm<{ decision: 'approve' | 'reject'; conclusion: string }>
          key="rv"
          title={`评审提案 ${p.meta ?? ''}`}
          trigger={<a>评审</a>}
          modalProps={{ destroyOnHidden: true }}
          onFinish={async (v) => {
            await act(() => reviewProposal(p.id, v.decision, v.conclusion), '已评审')
            return true
          }}
        >
          <ProFormSelect name="decision" label="决定" initialValue="approve" rules={[{ required: true }]}
            options={[{ value: 'approve', label: '通过' }, { value: 'reject', label: '驳回' }]} />
          <ProFormTextArea name="conclusion" label="评审意见" rules={[{ required: true }]} />
        </ModalForm>,
      ]
    if (p.kind === 'resolution')
      return [
        <Popconfirm key="c" title="确认此决议生效？（红线动作）" onConfirm={() => act(() => confirmResolution(p.id), '决议已确认')}>
          <a>确认生效</a>
        </Popconfirm>,
      ]
    return [
      <Popconfirm key="a" title="复核通过此协作请求？" onConfirm={() => act(() => reviewCollab(p.id, 'approve'), '已通过')}>
        <a>通过</a>
      </Popconfirm>,
      <Popconfirm key="r" title="驳回此协作请求？" onConfirm={() => act(() => reviewCollab(p.id, 'reject'), '已驳回')}>
        <a style={{ color: '#cf1322' }}>驳回</a>
      </Popconfirm>,
    ]
  }

  const isSupervising = viewUser && viewUser !== me?.id

  return (
    <PageContainer
      title="工作桌面"
      subTitle={isSupervising ? `监督：${data?.user.name ?? ''}` : '待我处理 · 我的任务 · 发起需求'}
      extra={
        me?.role_code === 'admin'
          ? [
              <Select
                key="sup"
                allowClear
                placeholder="监督查看某员工桌面"
                style={{ width: 220 }}
                value={viewUser}
                onChange={setViewUser}
                options={users.map((u) => ({ value: u.id, label: `${u.real_name || u.username}` }))}
              />,
            ]
          : undefined
      }
    >
      <Row gutter={16}>
        <Col xs={24} lg={14}>
          <Card title={<Badge count={data?.pending_count ?? 0} showZero offset={[10, 0]}>待我处理</Badge>}>
            {data && data.pending.length === 0 && <Empty description="暂无待处理" />}
            <List
              dataSource={data?.pending ?? []}
              renderItem={(p) => (
                <List.Item actions={actions(p)}>
                  <List.Item.Meta
                    title={
                      <Space>
                        <Tag color={KIND[p.kind].color}>{KIND[p.kind].label}</Tag>
                        {p.title}
                      </Space>
                    }
                    description={
                      <Space size="small">
                        {p.meta && <span>{p.meta}</span>}
                        {p.priority === 'high' && <Tag color={PRIORITY_COLOR.high}>高</Tag>}
                      </Space>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>

          <Card title="我的任务" style={{ marginTop: 16 }}>
            {data && data.my_tasks.length === 0 && <Empty description="暂无进行中的任务" />}
            <List
              dataSource={data?.my_tasks ?? []}
              renderItem={(t) => (
                <List.Item actions={[<a key="v" onClick={() => nav('/tasks')}>查看</a>]}>
                  <List.Item.Meta
                    title={t.title}
                    description={<Space><Tag>{STATUS_LABEL[t.status] ?? t.status}</Tag>{t.task_type}</Space>}
                  />
                </List.Item>
              )}
            />
          </Card>
        </Col>

        <Col xs={24} lg={10}>
          {!isSupervising && (
            <Card title="发起需求">
              <Space wrap>
                <Button type="primary" onClick={() => nav('/tasks')}>发起任务</Button>
                <Button onClick={() => nav('/proposals')}>发起提案</Button>
                <Button onClick={() => nav('/discussion')}>找 AI 顾问商议</Button>
              </Space>
              <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
                发起的需求由 AI 顾问或人机混合流程处理，产出仍须你确认后生效。
              </Typography.Paragraph>
            </Card>
          )}
          <Card title="快捷入口" style={{ marginTop: isSupervising ? 0 : 16 }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Button block onClick={() => nav('/discussion')}>
                协作空间 <Badge count={data?.counts.channels ?? 0} showZero style={{ marginLeft: 8 }} />
              </Button>
              <Button block onClick={() => nav('/knowledge')}>
                知识库 <Badge count={data?.counts.kbs ?? 0} showZero style={{ marginLeft: 8 }} />
              </Button>
            </Space>
          </Card>
        </Col>
      </Row>
    </PageContainer>
  )
}

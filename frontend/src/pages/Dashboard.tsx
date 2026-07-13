/** 真人工作桌面（F5a + 对话窗）：真人员工的统一工作枢纽。
 *  左主栏：待我处理 + 与 AI 顾问实时对话；右栏：发起需求 + 我的任务；admin 可监督他人。
 *  红线：桌面只发起/处理，生效动作走各自真人确认端点；AI 对话仅参考。 */
import { ModalForm, PageContainer, ProFormSelect, ProFormTextArea } from '@ant-design/pro-components'
import { Badge, Button, Card, Col, Empty, Input, List, Popconfirm, Row, Select, Space, Spin, Tag, Typography, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { consultAgent, listRoles, type AgentRole, type ChatTurn } from '../api/agents'
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

export default function Dashboard() {
  const { me } = useOutletContext<{ me: UserInfo | null }>()
  const nav = useNavigate()
  const [data, setData] = useState<Desktop | null>(null)
  const [viewUser, setViewUser] = useState<string | undefined>()
  const [users, setUsers] = useState<UserInfo[]>([])
  // AI 顾问对话
  const [agents, setAgents] = useState<AgentRole[]>([])
  const [chatAgent, setChatAgent] = useState<string | undefined>()
  const [chatMsgs, setChatMsgs] = useState<ChatTurn[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatSending, setChatSending] = useState(false)

  const reload = useCallback(async () => setData(await getDesktop(viewUser)), [viewUser])
  useEffect(() => {
    void reload()
  }, [reload])
  useEffect(() => {
    if (me?.role_code === 'admin') void listUsers().then(setUsers)
    void listRoles().then((rs) => {
      setAgents(rs)
      setChatAgent((c) => c ?? rs[0]?.id)
    })
  }, [me])

  const act = async (fn: () => Promise<unknown>, okMsg: string) => {
    await fn()
    message.success(okMsg)
    await reload()
  }

  const sendChat = async () => {
    if (!chatAgent || !chatInput.trim() || chatSending) return
    const q = chatInput.trim()
    const history = chatMsgs
    setChatMsgs([...history, { role: 'user', content: q }])
    setChatInput('')
    setChatSending(true)
    try {
      const { reply } = await consultAgent(chatAgent, q, history)
      setChatMsgs((m) => [...m, { role: 'ai', content: reply }])
    } catch {
      setChatMsgs((m) => [...m, { role: 'ai', content: '（AI 暂时无法回应，请稍后重试）' }])
    } finally {
      setChatSending(false)
    }
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
      subTitle={isSupervising ? `监督：${data?.user.name ?? ''}` : '待我处理 · 与 AI 对话 · 我的任务'}
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
        {/* 左主栏：待我处理 + AI 对话 */}
        <Col xs={24} lg={15}>
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
                        {p.priority === 'high' && <Tag color="red">高</Tag>}
                      </Space>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>

          {!isSupervising && (
            <Card title="与 AI 顾问对话" style={{ marginTop: 16 }}>
              <Select
                placeholder="选择 AI 顾问"
                style={{ width: '100%', marginBottom: 10 }}
                value={chatAgent}
                onChange={setChatAgent}
                showSearch
                optionFilterProp="label"
                options={agents.map((a) => ({ value: a.id, label: a.name }))}
              />
              <div style={{ height: 280, overflowY: 'auto', padding: '4px 2px', background: '#fafafa', borderRadius: 6, marginBottom: 10 }}>
                {chatMsgs.length === 0 && (
                  <Typography.Text type="secondary" style={{ display: 'block', textAlign: 'center', marginTop: 110 }}>
                    向 AI 顾问提问，它会结合知识库资料回答（仅供参考）
                  </Typography.Text>
                )}
                {chatMsgs.map((m, i) => (
                  <div key={i} style={{ textAlign: m.role === 'user' ? 'right' : 'left', margin: '8px 6px' }}>
                    <span
                      style={{
                        display: 'inline-block', maxWidth: '82%', padding: '7px 11px', borderRadius: 8,
                        textAlign: 'left', whiteSpace: 'pre-wrap',
                        background: m.role === 'user' ? '#1677ff' : '#fff',
                        color: m.role === 'user' ? '#fff' : undefined,
                        border: m.role === 'ai' ? '1px solid #eee' : undefined,
                      }}
                    >
                      {m.content}
                    </span>
                  </div>
                ))}
                {chatSending && <div style={{ textAlign: 'center', margin: 8 }}><Spin size="small" /></div>}
              </div>
              <Space.Compact style={{ width: '100%' }}>
                <Input
                  placeholder={chatAgent ? '向 AI 顾问提问，回车发送' : '请先选择 AI 顾问'}
                  value={chatInput}
                  disabled={!chatAgent}
                  onChange={(e) => setChatInput(e.target.value)}
                  onPressEnter={sendChat}
                />
                <Button type="primary" loading={chatSending} disabled={!chatAgent} onClick={sendChat}>
                  发送
                </Button>
              </Space.Compact>
            </Card>
          )}
        </Col>

        {/* 右栏：发起需求 + 我的任务 */}
        <Col xs={24} lg={9}>
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
          <Card title="我的任务" style={{ marginTop: isSupervising ? 0 : 16 }}>
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
      </Row>
    </PageContainer>
  )
}

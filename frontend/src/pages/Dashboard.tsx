/** 真人工作桌面（F5a + 对话窗）：真人员工的统一工作枢纽。
 *  左主栏：待我处理 + 与 AI 顾问实时对话；右栏：发起需求 + 我的任务；admin 可监督他人。
 *  红线：桌面只发起/处理，生效动作走各自真人确认端点；AI 对话仅参考。 */
import { ModalForm, PageContainer, ProFormSelect, ProFormTextArea } from '@ant-design/pro-components'
import { Badge, Button, Card, Col, Empty, Input, List, Popconfirm, Row, Select, Space, Spin, Tag, Typography, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import Markdown from '../components/Markdown'
import { listUsers, type UserInfo } from '../api/auth'
import { reviewCollab } from '../api/collab'
import {
  getDesktop,
  getDesktopChat,
  sendDesktopChat,
  type AddableAgent,
  type Desktop,
  type DesktopMessage,
  type PendingItem,
} from '../api/desktop'
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
  // 我的助理对话（持久 + 圆桌多AI）
  const [assistant, setAssistant] = useState<{ id: string; name: string } | null>(null)
  const [addable, setAddable] = useState<AddableAgent[]>([])
  const [addAgentIds, setAddAgentIds] = useState<string[]>([])
  const [chatMsgs, setChatMsgs] = useState<DesktopMessage[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatSending, setChatSending] = useState(false)

  const reload = useCallback(async () => setData(await getDesktop(viewUser)), [viewUser])
  useEffect(() => {
    void reload()
  }, [reload])
  useEffect(() => {
    if (me?.role_code === 'admin') void listUsers().then(setUsers)
  }, [me])
  // 载入我的助理对话（默认助理 + 最近历史 + 可加入的AI）
  useEffect(() => {
    void getDesktopChat().then((c) => {
      setAssistant(c.assistant)
      setChatMsgs(c.messages)
      setAddable(c.addable_agents)
    })
  }, [])

  const act = async (fn: () => Promise<unknown>, okMsg: string) => {
    await fn()
    message.success(okMsg)
    await reload()
  }

  const sendChat = async () => {
    if (!chatInput.trim() || chatSending) return
    const q = chatInput.trim()
    setChatInput('')
    setChatSending(true)
    try {
      const { messages } = await sendDesktopChat(q, addAgentIds)
      setChatMsgs((m) => [...m, ...messages])
    } catch {
      // 错误已由拦截器提示
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
            <Card
              title={assistant ? `与${assistant.name}对话` : '我的助理'}
              style={{ marginTop: 16 }}
              extra={
                <Select
                  mode="multiple"
                  allowClear
                  maxCount={2}
                  style={{ minWidth: 220 }}
                  placeholder="+ 加入AI圆桌（最多2个）"
                  value={addAgentIds}
                  onChange={setAddAgentIds}
                  optionFilterProp="label"
                  options={addable.map((a) => ({ value: a.id, label: a.name }))}
                />
              }
            >
              <div style={{ height: 300, overflowY: 'auto', padding: '4px 2px', background: '#fafafa', borderRadius: 6, marginBottom: 10 }}>
                {chatMsgs.length === 0 && (
                  <Typography.Text type="secondary" style={{ display: 'block', textAlign: 'center', marginTop: 120 }}>
                    向你的助理提问，它会结合知识库与过往对话回答（仅供参考）。可加入其他 AI 一起圆桌讨论。
                  </Typography.Text>
                )}
                {chatMsgs.map((m) => {
                  const mine = m.speaker_type === 'user'
                  return (
                    <div key={m.id} style={{ textAlign: mine ? 'right' : 'left', margin: '10px 6px' }}>
                      {!mine && (
                        <div style={{ fontSize: 12, color: '#888', marginBottom: 2 }}>{m.speaker_name}</div>
                      )}
                      <span
                        style={{
                          display: 'inline-block', maxWidth: '82%', padding: '7px 11px', borderRadius: 8,
                          textAlign: 'left', whiteSpace: mine ? 'pre-wrap' : 'normal',
                          background: mine ? '#1677ff' : '#fff',
                          color: mine ? '#fff' : undefined,
                          border: mine ? undefined : '1px solid #eee',
                        }}
                      >
                        {mine ? m.content : <Markdown>{m.content}</Markdown>}
                      </span>
                    </div>
                  )
                })}
                {chatSending && <div style={{ textAlign: 'center', margin: 8 }}><Spin size="small" /></div>}
              </div>
              <Space.Compact style={{ width: '100%' }}>
                <Input
                  placeholder="向你的助理提问，回车发送"
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onPressEnter={sendChat}
                />
                <Button type="primary" loading={chatSending} onClick={sendChat}>
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

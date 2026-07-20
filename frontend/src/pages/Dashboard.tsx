/** 真人工作桌面（F5a + 对话窗）：真人员工的统一工作枢纽。
 *  左主栏：待我处理 + 与 AI 顾问实时对话；右栏：发起需求 + 我的任务；admin 可监督他人。
 *  红线：桌面只发起/处理，生效动作走各自真人确认端点；AI 对话仅参考。 */
import { ModalForm, PageContainer, ProFormSelect, ProFormTextArea } from '@ant-design/pro-components'
import { Badge, Button, Card, Col, Empty, Input, List, Popconfirm, Row, Select, Space, Spin, Tag, Typography, message } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import Markdown from '../components/Markdown'
import { listUsers, type UserInfo } from '../api/auth'
import { roster } from '../api/auth'
import { reviewCollab } from '../api/collab'
import {
  getDesktop,
  getDesktopChat,
  listDeliverables,
  downloadDeliverable,
  sendDesktopChat,
  type AddableAgent,
  type Deliverable,
  type Desktop,
  type DesktopMessage,
  type PendingItem,
} from '../api/desktop'
import { confirmResolution } from '../api/meetings'
import { reviewProposal } from '../api/proposals'
import { STATUS_LABEL, transitionTask, getOrchestrationProgress, type OrchProgress } from '../api/tasks'
import GroupChat from '../components/GroupChat'
import {
  createChannel,
  myChannels,
  subscribeRealtime,
  type ChannelWithUnread,
  type Message as ChanMessage,
} from '../api/discussion'
import { listRoles, type AgentRole } from '../api/agents'

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
  const [deliverables, setDeliverables] = useState<Deliverable[]>([])
  const [orch, setOrch] = useState<OrchProgress | null>(null)  // 当前编排进度（进度卡）
  // 会话列表（讨论组，I1-I7）：统一列表 = 我的助理 + 讨论组
  const [channels, setChannels] = useState<ChannelWithUnread[]>([])
  const [activeConv, setActiveConv] = useState<{ type: 'assistant' } | { type: 'group'; id: string; name: string }>({ type: 'assistant' })
  const [liveMsg, setLiveMsg] = useState<(ChanMessage & { channel_id?: string }) | null>(null)
  const [newGroupOpen, setNewGroupOpen] = useState(false)
  const [newGroupName, setNewGroupName] = useState('')
  const [newGroupAis, setNewGroupAis] = useState<string[]>([])
  const [newGroupHumans, setNewGroupHumans] = useState<string[]>([])
  const [allAgents, setAllAgents] = useState<AgentRole[]>([])
  const [roster2, setRoster2] = useState<{ id: string; real_name: string; username: string }[]>([])
  const chatBoxRef = useRef<HTMLDivElement>(null)

  const loadChannels = useCallback(() => void myChannels().then(setChannels), [])
  useEffect(() => {
    loadChannels()
    void listRoles().then(setAllAgents)
    void roster().then(setRoster2).catch(() => {})
  }, [loadChannels])
  // 桌面级实时订阅：任何群来消息 → 传给 GroupChat（当前群）或未读+1（其它群）
  useEffect(() => {
    const cancel = subscribeRealtime((event, data) => {
      if (event !== 'message') return
      const msg = data as unknown as ChanMessage & { channel_id?: string }
      setLiveMsg(msg)
      const active = activeConv.type === 'group' ? activeConv.id : null
      if (msg.channel_id && msg.channel_id !== active) {
        setChannels((cs) => cs.map((c) => (c.id === msg.channel_id ? { ...c, unread: (c.unread ?? 0) + 1 } : c)))
      }
    })
    return cancel
  }, [activeConv])
  // 载入/新消息后自动滚到底（始终停在最新对话上）
  useEffect(() => {
    const el = chatBoxRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [chatMsgs])

  const reload = useCallback(async () => setData(await getDesktop(viewUser)), [viewUser])
  const loadDeliverables = useCallback(async () => {
    setDeliverables(await listDeliverables(viewUser))
  }, [viewUser])
  useEffect(() => {
    void reload()
  }, [reload])
  useEffect(() => {
    void loadDeliverables()
  }, [loadDeliverables])
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
    // 乐观上屏：用户气泡即时显示；SSE 到达后由 message_end(user) 替换
    const tmpId = `tmp-${Date.now()}`
    const streamId = '__streaming__'
    setChatMsgs((m) => [...m, { id: tmpId, speaker_type: 'user', speaker_agent_id: null, speaker_name: '我', content: q, create_time: '' }])
    try {
      await sendDesktopChat(q, addAgentIds, (event, data) => {
        if (event === 'message_start') {
          // 开一个流式气泡（逐字追加）
          const d = data as unknown as { speaker_agent_id: string | null; speaker_name: string }
          setChatMsgs((m) => [...m, { id: streamId, speaker_type: 'ai', speaker_agent_id: d.speaker_agent_id, speaker_name: d.speaker_name, content: '', create_time: '' }])
        } else if (event === 'delta') {
          const text = String((data as { text?: unknown }).text ?? '')
          setChatMsgs((m) => m.map((x) => (x.id === streamId ? { ...x, content: x.content + text } : x)))
        } else if (event === 'message_end') {
          const msg = data as unknown as DesktopMessage
          // 用落库消息替换流式气泡（AI）或乐观气泡（用户回显）
          setChatMsgs((m) => m.map((x) => (x.id === (msg.speaker_type === 'user' ? tmpId : streamId) ? msg : x)))
        } else if (event === 'orchestration') {
          // 复合任务编排进度：渲染折叠进度卡（红线步骤含验收按钮）
          setOrch(data as unknown as OrchProgress)
        }
      })
    } catch {
      // 错误已由 sseRequest 提示：清掉未完成的流式/乐观气泡并还原输入
      setChatMsgs((m) => m.filter((x) => x.id !== streamId && x.id !== tmpId))
      setChatInput(q)
    } finally {
      setChatSending(false)
      void loadDeliverables()  // AI 可能刚交付了文件，刷新交付区
    }
  }

  /** 验收编排的某红线步骤 → 后端 resume 推进 → 刷新进度卡。 */
  const acceptStep = async (stepId: string) => {
    if (!orch) return
    await transitionTask(stepId, 'accepted')
    message.success('已验收，继续推进')
    setOrch(await getOrchestrationProgress(orch.parent_id))
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
      <Row gutter={16} style={{ overflow: 'hidden' }}>
        {/* 左主栏：待我处理 + AI 对话（flex 列布满视口，待办缩小时对话自动增高） */}
        <Col xs={24} lg={15}>
          <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 130px)', minHeight: 480 }}>
          <Card
            size="small"
            title={<Badge count={data?.pending_count ?? 0} showZero offset={[10, 0]}>待我处理</Badge>}
            // 空态收缩到最小；有内容按量增高，最多占窗口一半后内部滚动
            style={{ flex: 'none' }}
            styles={{ body: { maxHeight: '50vh', overflowY: 'auto', padding: data && data.pending.length === 0 ? '8px 16px' : undefined } }}
          >
            {data && data.pending.length === 0 && <Typography.Text type="secondary">暂无待处理</Typography.Text>}
            {(!data || data.pending.length > 0) && <List
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
            />}
          </Card>

          {!isSupervising && (
          <div style={{ flex: 1, minHeight: 0, minWidth: 0, display: 'flex', gap: 12, marginTop: 16 }}>
            {/* 左：会话列表（我的助理 + 讨论组，带未读红点） */}
            <Card
              size="small" title="对话"
              style={{ width: 152, flexShrink: 0, overflowY: 'auto' }}
              styles={{ body: { padding: 6 } }}
              extra={<a style={{ fontSize: 12 }} onClick={() => setNewGroupOpen(true)}>+群</a>}
            >
              <div
                onClick={() => setActiveConv({ type: 'assistant' })}
                style={{ cursor: 'pointer', padding: '6px 6px', borderRadius: 4, fontSize: 12,
                  background: activeConv.type === 'assistant' ? '#e6f4ff' : undefined }}
              >💬 我的助理</div>
              {channels.map((ch) => {
                const on = activeConv.type === 'group' && activeConv.id === ch.id
                return (
                  <div key={ch.id}
                    onClick={() => setActiveConv({ type: 'group', id: ch.id, name: ch.name })}
                    style={{ cursor: 'pointer', padding: '6px 6px', borderRadius: 4, fontSize: 12,
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      background: on ? '#e6f4ff' : undefined }}
                  >
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}># {ch.name}</span>
                    {ch.unread > 0 && !on && <Badge count={ch.unread} size="small" />}
                  </div>
                )
              })}
            </Card>
            {/* 右：当前会话 */}
            <div style={{ flex: 1, minHeight: 0, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
            {activeConv.type === 'group' ? (
              <GroupChat
                channelId={activeConv.id} channelName={activeConv.name} liveMessage={liveMsg}
                onRead={(cid) => setChannels((cs) => cs.map((c) => (c.id === cid ? { ...c, unread: 0 } : c)))}
              />
            ) : (
            <Card
              title={assistant ? `与${assistant.name}对话` : '我的助理'}
              // 占满剩余高度：卡片整体 flex 列，消息区 flex:1 内部滚动
              style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}
              styles={{ body: { flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' } }}
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
              <div ref={chatBoxRef} style={{ flex: 1, minHeight: 200, overflowY: 'auto', padding: '4px 2px', background: '#fafafa', borderRadius: 6, marginBottom: 10, fontSize: 12 }}>
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
              {orch && (
                <Card
                  size="small"
                  style={{ marginBottom: 10, background: '#f6ffed' }}
                  title={
                    <span style={{ fontSize: 12 }}>
                      任务进度 {orch.accepted}/{orch.total}
                      {orch.done && <Tag color="green" style={{ marginLeft: 8 }}>已完成</Tag>}
                      {orch.awaiting_human.length > 0 && (
                        <Tag color="orange" style={{ marginLeft: 8 }}>待验收</Tag>
                      )}
                    </span>
                  }
                  extra={<a style={{ fontSize: 12 }} onClick={() => setOrch(null)}>收起</a>}
                >
                  <List
                    size="small"
                    dataSource={orch.steps}
                    renderItem={(s) => {
                      const icon = s.status === 'accepted' ? '✅'
                        : s.status === 'reported' ? '⏸'
                        : s.status === 'executing' ? '▶' : '○'
                      const waiting = s.red_line && s.status === 'reported'
                      return (
                        <List.Item
                          style={{ fontSize: 12, padding: '4px 0' }}
                          actions={
                            waiting
                              ? [<a key="ac" onClick={() => acceptStep(s.id)}>验收并继续</a>]
                              : []
                          }
                        >
                          <Space size={6}>
                            <span>{icon}</span>
                            <span>步骤{s.step_no + 1}·{s.title}</span>
                            <Tag>{s.skill}</Tag>
                            {s.red_line && <Tag color="red">红线</Tag>}
                          </Space>
                        </List.Item>
                      )
                    }}
                  />
                </Card>
              )}
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
            </div>
          </div>
          )}
          </div>
        </Col>

        {/* 右栏：发起需求 + 我的任务 + 文件交付区（固定高度内部滚动，不顶高页面） */}
        <Col xs={24} lg={9}>
          <div style={{ height: 'calc(100vh - 130px)', minHeight: 480, overflowY: 'auto', paddingRight: 4 }}>
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
          <Card
            title={<Badge count={deliverables.length} showZero offset={[10, 0]}>文件交付区</Badge>}
            style={{ marginTop: 16 }}
            extra={<a onClick={() => void loadDeliverables()}>刷新</a>}
          >
            {deliverables.length === 0 && <Empty description="AI 交付的文档/表格会出现在这里" />}
            <List
              dataSource={deliverables}
              renderItem={(d) => (
                <List.Item
                  actions={[
                    <a key="dl" onClick={() => void downloadDeliverable(d.id, d.file_name)}>下载</a>,
                  ]}
                >
                  <List.Item.Meta
                    title={<Space><Tag color="cyan">{d.file_format.toUpperCase()}</Tag>{d.file_name}</Space>}
                    description={
                      <Typography.Text type="secondary">
                        {d.agent_name || 'AI'} 交付 · {new Date(d.create_time).toLocaleString()}
                      </Typography.Text>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>
          </div>
        </Col>
      </Row>

      {/* 新建讨论组：起名 + 拉真人/AI 进群 */}
      <ModalForm
        open={newGroupOpen}
        title="新建讨论组"
        modalProps={{ destroyOnHidden: true, onCancel: () => setNewGroupOpen(false) }}
        onOpenChange={setNewGroupOpen}
        submitter={{ searchConfig: { submitText: '创建' } }}
        onFinish={async () => {
          if (!newGroupName.trim()) { message.warning('请输入群名'); return false }
          const mems = [
            ...newGroupHumans.map((id) => ({ member_type: 'human' as const, member_id: id })),
            ...newGroupAis.map((id) => ({ member_type: 'ai' as const, member_id: id })),
          ]
          const c = await createChannel({ name: newGroupName.trim(), members: mems })
          message.success('讨论组已创建')
          setNewGroupName(''); setNewGroupHumans([]); setNewGroupAis([])
          setNewGroupOpen(false)
          loadChannels()
          setActiveConv({ type: 'group', id: c.id, name: c.name })
          return true
        }}
      >
        <Input placeholder="群名称" value={newGroupName} onChange={(e) => setNewGroupName(e.target.value)} style={{ marginBottom: 12 }} />
        <div style={{ marginBottom: 4, fontSize: 13 }}>拉真人员工</div>
        <Select
          mode="multiple" allowClear style={{ width: '100%', marginBottom: 12 }} placeholder="选择同事"
          value={newGroupHumans} onChange={setNewGroupHumans} optionFilterProp="label"
          options={roster2.map((u) => ({ value: u.id, label: u.real_name || u.username }))}
        />
        <div style={{ marginBottom: 4, fontSize: 13 }}>拉 AI 员工</div>
        <Select
          mode="multiple" allowClear style={{ width: '100%' }} placeholder="选择 AI"
          value={newGroupAis} onChange={setNewGroupAis} optionFilterProp="label"
          options={allAgents.map((a) => ({ value: a.id, label: a.name }))}
        />
      </ModalForm>
    </PageContainer>
  )
}

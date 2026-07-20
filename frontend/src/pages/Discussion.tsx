/** 协作空间：左栏频道列表，右栏消息流 + @Agent 触发 + 升格提案/任务。
 *  红线：AI 发言仅参考，升格产出仍走真人确认闸门。 */
import { PageContainer } from '@ant-design/pro-components'
import { Avatar, Button, Card, Empty, Input, List, Popconfirm, Select, Space, Tag, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import Markdown from '../components/Markdown'
import { listRoles, type AgentRole } from '../api/agents'
import {
  listChannels,
  listMessages,
  postMessage,
  promoteMessage,
  subscribeRealtime,
  type Channel,
  type Message,
} from '../api/discussion'

export default function Discussion() {
  const [channels, setChannels] = useState<Channel[]>([])
  const [agents, setAgents] = useState<AgentRole[]>([])
  const [current, setCurrent] = useState<Channel | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [text, setText] = useState('')
  const [mentions, setMentions] = useState<string[]>([])
  const [sending, setSending] = useState(false)

  useEffect(() => {
    void listChannels().then((cs) => {
      setChannels(cs)
      if (cs.length) setCurrent((c) => c ?? cs[0])
    })
    void listRoles().then(setAgents)
  }, [])

  const loadMessages = (channelId: string) => void listMessages(channelId).then(setMessages)

  // 实时订阅（I3）：别人在当前群发言即时追加（按 id 去重，防与本地流式重复）
  useEffect(() => {
    const cancel = subscribeRealtime((event, data) => {
      if (event !== 'message') return
      const msg = data as unknown as Message & { channel_id?: string }
      if (!current || msg.channel_id !== current.id) return
      setMessages((m) => (m.some((x) => x.id === msg.id) ? m : [...m, msg]))
    })
    return cancel
  }, [current])
  useEffect(() => {
    if (current) loadMessages(current.id)
  }, [current])

  const send = async () => {
    if (!current || !text.trim()) return
    const channelId = current.id
    const streamId = '__streaming__'
    setSending(true)
    try {
      await postMessage(channelId, text.trim(), mentions.slice(0, 3), (event, data) => {
        if (event === 'message_start') {
          const d = data as unknown as { speaker_agent_id: string | null; speaker_name: string }
          setMessages((m) => [...m, {
            id: streamId, channel_id: channelId, speaker_type: 'ai',
            speaker_id: d.speaker_agent_id, speaker_name: d.speaker_name, content: '',
            mentioned_agent_ids: [], ai_source_record_id: null, ref_type: null, ref_id: null, create_time: '',
          }])
        } else if (event === 'delta') {
          const t = String((data as { text?: unknown }).text ?? '')
          setMessages((m) => m.map((x) => (x.id === streamId ? { ...x, content: x.content + t } : x)))
        } else if (event === 'message_end') {
          const msg = data as unknown as Message
          // AI 落库消息替换流式气泡；真人消息（无流式气泡）直接追加
          setMessages((m) => (m.some((x) => x.id === streamId)
            ? m.map((x) => (x.id === streamId ? msg : x))
            : [...m, msg]))
        }
      })
      setText('')
      setMentions([])
    } catch {
      setMessages((m) => m.filter((x) => x.id !== streamId))
    } finally {
      setSending(false)
    }
  }

  const promote = async (m: Message, target: 'proposal' | 'task') => {
    await promoteMessage(m.id, target)
    message.success(target === 'proposal' ? '已升格为提案' : '已升格为任务卡')
    if (current) loadMessages(current.id)
  }

  return (
    <PageContainer title="协作空间" subTitle="人机讨论 · @顾问触发参考意见 · 讨论升格为提案/任务">
      <div style={{ display: 'flex', gap: 16 }}>
        <Card title="频道" size="small" style={{ width: 220, flexShrink: 0 }} styles={{ body: { padding: 8 } }}>
          <List
            size="small"
            dataSource={channels}
            locale={{ emptyText: '暂无频道' }}
            renderItem={(c) => (
              <List.Item
                onClick={() => setCurrent(c)}
                style={{
                  cursor: 'pointer', padding: '6px 8px', borderRadius: 6,
                  background: current?.id === c.id ? '#e6f4ff' : undefined,
                }}
              >
                # {c.name}
                {c.is_archived && <Tag style={{ marginLeft: 4 }}>已归档</Tag>}
              </List.Item>
            )}
          />
        </Card>

        <Card
          title={current ? `# ${current.name}` : '选择频道'}
          size="small"
          style={{ flex: 1, minWidth: 0 }}
        >
          {!current && <Empty description="左侧选择一个频道" />}
          {current && (
            <>
              <div style={{ maxHeight: '55vh', overflowY: 'auto', marginBottom: 12 }}>
                <List
                  dataSource={messages}
                  locale={{ emptyText: '还没有消息，@ 一位顾问开始讨论' }}
                  renderItem={(m) => (
                    <List.Item
                      actions={
                        m.speaker_type === 'human' && !m.ref_id
                          ? [
                              <Popconfirm key="p" title="把这条讨论升格为提案？" onConfirm={() => promote(m, 'proposal')}>
                                <a>升提案</a>
                              </Popconfirm>,
                              <Popconfirm key="t" title="把这条讨论升格为任务卡？" onConfirm={() => promote(m, 'task')}>
                                <a>升任务</a>
                              </Popconfirm>,
                            ]
                          : undefined
                      }
                    >
                      <List.Item.Meta
                        avatar={
                          <Avatar style={{ background: m.speaker_type === 'ai' ? '#722ed1' : '#1677ff' }}>
                            {m.speaker_type === 'ai' ? 'AI' : m.speaker_name.slice(0, 1) || '人'}
                          </Avatar>
                        }
                        title={
                          <Space>
                            {m.speaker_name}
                            {m.speaker_type === 'ai' && <Tag color="purple">AI 顾问 · 参考</Tag>}
                            {m.ref_type && <Tag color="green">已升{m.ref_type === 'proposal' ? '提案' : '任务'}</Tag>}
                          </Space>
                        }
                        description={
                          <Typography.Paragraph style={{ marginBottom: 0 }}>
                            <Markdown>{m.content}</Markdown>
                          </Typography.Paragraph>
                        }
                      />
                    </List.Item>
                  )}
                />
              </div>

              <Space.Compact style={{ width: '100%' }}>
                <Select
                  mode="multiple"
                  allowClear
                  maxCount={3}
                  placeholder="@顾问（最多3位）"
                  style={{ width: 260 }}
                  value={mentions}
                  onChange={setMentions}
                  options={agents.map((a) => ({ value: a.id, label: a.name }))}
                />
                <Input
                  placeholder="输入消息，@顾问可触发一次参考意见…"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  onPressEnter={send}
                />
                <Button type="primary" loading={sending} onClick={send}>
                  发送
                </Button>
              </Space.Compact>
            </>
          )}
        </Card>
      </div>
    </PageContainer>
  )
}

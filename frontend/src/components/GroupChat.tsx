/** 群聊窗口（工作桌面讨论组，复用 discussion I1-I7 后端）：
 *  单个群的消息流 + 发送 + 实时接收 + 进群已读清零 + 拉成员。真人+AI 混合。 */
import { Avatar, Button, Input, Modal, Select, Space, Spin, Tag, Typography, message } from 'antd'
import { useEffect, useRef, useState } from 'react'
import Markdown from './Markdown'
import { listRoles, type AgentRole } from '../api/agents'
import { roster, type Colleague } from '../api/auth'
import {
  addMembers,
  listMembers,
  listMessages,
  markRead,
  postMessage,
  type Message,
} from '../api/discussion'

export default function GroupChat({
  channelId,
  channelName,
  onRead,
  liveMessage,
}: {
  channelId: string
  channelName: string
  onRead: (channelId: string) => void
  liveMessage: (Message & { channel_id?: string }) | null  // 父级实时推来的消息
}) {
  const [msgs, setMsgs] = useState<Message[]>([])
  const [text, setText] = useState('')
  const [mentions, setMentions] = useState<string[]>([])
  const [sending, setSending] = useState(false)
  const [agents, setAgents] = useState<AgentRole[]>([])
  const [members, setMembers] = useState<{ member_type: string; member_id: string; member_name: string }[]>([])
  const [pickOpen, setPickOpen] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => { void listRoles().then(setAgents) }, [])
  // 切群：加载消息 + 已读清零 + 成员
  useEffect(() => {
    void listMessages(channelId).then(setMsgs)
    void markRead(channelId).then(() => onRead(channelId))
    void listMembers(channelId).then(setMembers)
  }, [channelId])
  useEffect(() => {
    const el = boxRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [msgs])
  // 父级实时推来的消息若属于本群，追加（按 id 去重）
  useEffect(() => {
    if (!liveMessage || liveMessage.channel_id !== channelId) return
    setMsgs((m) => (m.some((x) => x.id === liveMessage.id) ? m : [...m, liveMessage]))
    void markRead(channelId).then(() => onRead(channelId))
  }, [liveMessage, channelId])

  const send = async () => {
    if (!text.trim() || sending) return
    const q = text.trim()
    setText('')
    setSending(true)
    const streamId = '__streaming__'
    try {
      await postMessage(channelId, q, mentions.slice(0, 3), (event, data) => {
        if (event === 'message_start') {
          const d = data as unknown as { speaker_agent_id: string | null; speaker_name: string }
          setMsgs((m) => [...m, {
            id: streamId, channel_id: channelId, speaker_type: 'ai',
            speaker_id: d.speaker_agent_id, speaker_name: d.speaker_name, content: '',
            mentioned_agent_ids: [], ai_source_record_id: null, ref_type: null, ref_id: null, create_time: '',
          }])
        } else if (event === 'delta') {
          const t = String((data as { text?: unknown }).text ?? '')
          setMsgs((m) => m.map((x) => (x.id === streamId ? { ...x, content: x.content + t } : x)))
        } else if (event === 'message_end') {
          const msg = data as unknown as Message
          setMsgs((m) => {
            const has = m.some((x) => x.id === msg.id)
            const cleared = m.filter((x) => x.id !== streamId)
            return has ? cleared : [...cleared, msg]
          })
        }
      })
    } catch { /* sseRequest 已提示 */ } finally { setSending(false) }
  }

  const memberIds = new Set(members.map((m) => m.member_id))

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <Space>
          <b>{channelName}</b>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{members.length} 成员</Typography.Text>
        </Space>
        <Button size="small" onClick={() => setPickOpen(true)}>+ 拉人/AI</Button>
      </div>
      <div ref={boxRef} style={{ flex: 1, minHeight: 160, overflowY: 'auto', padding: '4px 2px', background: '#fafafa', borderRadius: 6, marginBottom: 10, fontSize: 12 }}>
        {msgs.length === 0 && (
          <Typography.Text type="secondary" style={{ display: 'block', textAlign: 'center', marginTop: 80 }}>
            群里还没有消息。发一条，或 @AI 让它参与讨论。
          </Typography.Text>
        )}
        {msgs.map((m) => {
          const ai = m.speaker_type === 'ai'
          return (
            <div key={m.id} style={{ margin: '10px 6px' }}>
              <div style={{ fontSize: 12, color: '#888', marginBottom: 2 }}>
                {ai && <Tag color="blue" style={{ marginRight: 4 }}>AI</Tag>}{m.speaker_name}
              </div>
              <span style={{ display: 'inline-block', maxWidth: '82%', padding: '7px 11px', borderRadius: 8, background: '#fff', border: '1px solid #eee' }}>
                {ai ? <Markdown>{m.content}</Markdown> : m.content}
              </span>
            </div>
          )
        })}
        {sending && <div style={{ textAlign: 'center', margin: 8 }}><Spin size="small" /></div>}
      </div>
      <Space.Compact style={{ width: '100%' }}>
        <Select
          mode="multiple" allowClear maxCount={3} style={{ minWidth: 150 }}
          placeholder="@AI（可选，最多3）" value={mentions} onChange={setMentions}
          optionFilterProp="label"
          options={agents.filter((a) => memberIds.has(a.id)).map((a) => ({ value: a.id, label: a.name }))}
        />
        <Input placeholder="发消息，回车发送" value={text} onChange={(e) => setText(e.target.value)} onPressEnter={send} />
        <Button type="primary" loading={sending} onClick={send}>发送</Button>
      </Space.Compact>

      <MemberPicker
        open={pickOpen}
        onClose={() => setPickOpen(false)}
        existing={memberIds}
        agents={agents}
        onAdd={async (mems) => {
          await addMembers(channelId, mems)
          message.success('已拉入')
          setPickOpen(false)
          void listMembers(channelId).then(setMembers)
        }}
      />
    </div>
  )
}

/** 拉人/AI 进群选择器：真人员工 + AI 员工混合。 */
function MemberPicker({
  open, onClose, existing, agents, onAdd,
}: {
  open: boolean
  onClose: () => void
  existing: Set<string>
  agents: AgentRole[]
  onAdd: (m: { member_type: 'human' | 'ai'; member_id: string; member_name?: string }[]) => Promise<void>
}) {
  const [users, setUsers] = useState<Colleague[]>([])
  const [pickHumans, setPickHumans] = useState<string[]>([])
  const [pickAis, setPickAis] = useState<string[]>([])
  useEffect(() => {
    if (open) void roster().then(setUsers).catch(() => {})
  }, [open])

  const submit = async () => {
    const mems = [
      ...pickHumans.map((id) => {
        const u = users.find((x) => x.id === id)
        return { member_type: 'human' as const, member_id: id, member_name: u?.real_name || u?.username }
      }),
      ...pickAis.map((id) => ({ member_type: 'ai' as const, member_id: id, member_name: agents.find((a) => a.id === id)?.name })),
    ]
    if (mems.length) await onAdd(mems)
    setPickHumans([]); setPickAis([])
  }

  return (
    <Modal open={open} onCancel={onClose} onOk={submit} title="拉人 / AI 进群" okText="拉入">
      <div style={{ marginBottom: 12 }}>
        <div style={{ marginBottom: 4 }}>真人员工</div>
        <Select
          mode="multiple" allowClear style={{ width: '100%' }} placeholder="选择同事"
          value={pickHumans} onChange={setPickHumans} optionFilterProp="label"
          options={users.filter((u) => !existing.has(u.id)).map((u) => ({ value: u.id, label: u.real_name || u.username }))}
        />
      </div>
      <div>
        <div style={{ marginBottom: 4 }}>AI 员工</div>
        <Select
          mode="multiple" allowClear style={{ width: '100%' }} placeholder="选择 AI"
          value={pickAis} onChange={setPickAis} optionFilterProp="label"
          options={agents.filter((a) => !existing.has(a.id)).map((a) => ({ value: a.id, label: a.name }))}
        />
      </div>
      <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
        <Avatar size={14} style={{ marginRight: 4 }} />真人需先登录过本系统才可被拉入。
      </Typography.Text>
    </Modal>
  )
}

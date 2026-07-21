/** 群聊窗口（工作桌面讨论组，复用 discussion I1-I7 后端）：
 *  单个群的消息流 + 发送 + 实时接收 + 进群已读清零 + 拉成员。真人+AI 混合。 */
import { Avatar, Button, Input, Modal, Popconfirm, Select, Space, Spin, Tag, Typography, Upload, message } from 'antd'
import { PaperClipOutlined } from '@ant-design/icons'
import { useEffect, useRef, useState } from 'react'
import Markdown from './Markdown'
import { listRoles, type AgentRole } from '../api/agents'
import { roster, type Colleague } from '../api/auth'
import {
  addMembers,
  disbandChannel,
  downloadAttachment,
  listMembers,
  listMessages,
  markRead,
  postMessage,
  removeMember,
  uploadAttachment,
  type Attachment,
  type Message,
} from '../api/discussion'

export default function GroupChat({
  channelId,
  channelName,
  onRead,
  liveMessage,
  realtimeConnected,
  isOwner,
  ownerId,
  onMembershipChange,
  onDisband,
}: {
  channelId: string
  channelName: string
  onRead: (channelId: string) => void
  liveMessage: (Message & { channel_id?: string }) | null  // 父级实时推来的消息
  realtimeConnected: boolean
  isOwner: boolean
  ownerId: string | null
  onMembershipChange: () => void
  onDisband: () => void
}) {
  const [msgs, setMsgs] = useState<Message[]>([])
  const [text, setText] = useState('')
  const [mentions, setMentions] = useState<string[]>([])
  const [sending, setSending] = useState(false)
  const [agents, setAgents] = useState<AgentRole[]>([])
  const [members, setMembers] = useState<{ member_type: string; member_id: string; member_name: string }[]>([])
  const [pickOpen, setPickOpen] = useState(false)
  const [membersOpen, setMembersOpen] = useState(false)
  const [pending, setPending] = useState<Attachment[]>([])  // 待发送附件
  const [uploading, setUploading] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let disposed = false
    void listRoles().then((items) => { if (!disposed) setAgents(items) }).catch(() => {})
    return () => { disposed = true }
  }, [])

  useEffect(() => { setMsgs([]) }, [channelId])

  // SSE 不可用时轮询当前群；恢复连接时再补拉一次，随后停止轮询。
  useEffect(() => {
    const ctrl = new AbortController()
    let timer: number | undefined
    let disposed = false
    const refresh = async () => {
      try {
        const remote = await listMessages(channelId, { signal: ctrl.signal, silent: true })
        if (disposed) return
        setMsgs((current) => {
          const remoteIds = new Set(remote.map((item) => item.id))
          const justArrived = current.filter((item) => (
            item.channel_id === channelId && !remoteIds.has(item.id)
          ))
          return [...remote, ...justArrived]
        })
        await markRead(channelId, { signal: ctrl.signal, silent: true })
        if (!disposed) onRead(channelId)
      } catch { /* 静默降级，下一轮继续 */ }
      if (!disposed && !realtimeConnected) {
        timer = window.setTimeout(() => { void refresh() }, 5000)
      }
    }
    void refresh()
    return () => {
      disposed = true
      ctrl.abort()
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [channelId, onRead, realtimeConnected])

  // 切群：刷新成员；signal 确保快速切换/卸载不会回写旧群数据。
  useEffect(() => {
    const ctrl = new AbortController()
    void listMembers(channelId, { signal: ctrl.signal, silent: true }).then((items) => {
      if (!ctrl.signal.aborted) setMembers(items)
    }).catch(() => {})
    return () => ctrl.abort()
  }, [channelId])
  useEffect(() => {
    const el = boxRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [msgs])
  // 父级实时推来的消息若属于本群，追加（按 id 去重）
  useEffect(() => {
    if (!liveMessage || liveMessage.channel_id !== channelId) return
    const ctrl = new AbortController()
    setMsgs((m) => (m.some((x) => x.id === liveMessage.id) ? m : [...m, liveMessage]))
    void markRead(channelId, { signal: ctrl.signal, silent: true }).then(() => onRead(channelId)).catch(() => {})
    return () => ctrl.abort()
  }, [liveMessage, channelId, onRead])

  const send = async () => {
    if ((!text.trim() && pending.length === 0) || sending) return
    // 选中的成员：拼「@名字」前缀（真人+AI 都加）；只有 AI 的 id 触发回复
    const sel = members.filter((m) => mentions.includes(m.member_id))
    const prefix = sel.map((m) => `@${m.member_name || '成员'}`).join(' ')
    const aiIds = sel.filter((m) => m.member_type === 'ai').map((m) => m.member_id)
    const body = text.trim()
    const q = [prefix, body].filter(Boolean).join(' ') || (pending.length ? '[附件]' : '')
    const atts = pending
    setText('')
    setPending([])
    setMentions([])
    setSending(true)
    const streamId = '__streaming__'
    try {
      await postMessage(channelId, q, aiIds.slice(0, 3), (event, data) => {
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
      }, atts)
    } catch { /* sseRequest 已提示 */ } finally { setSending(false) }
  }

  const onUpload = async (file: File): Promise<boolean> => {
    if (file.size > 20 * 1024 * 1024) { message.error('文件过大（>20MB）'); return false }
    setUploading(true)
    try {
      const att = await uploadAttachment(file)
      setPending((p) => [...p, att])
    } catch { message.error('上传失败') } finally { setUploading(false) }
    return false  // 阻止 antd Upload 自己上传
  }

  const memberIds = new Set(members.map((m) => m.member_id))

  return (
    <div style={{ flex: 1, minHeight: 0, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <Space>
          <b>{channelName}</b>
          <a style={{ fontSize: 12 }} onClick={() => setMembersOpen(true)}>{members.length} 成员</a>
          {isOwner && <Tag color="gold">群主</Tag>}
        </Space>
        <Space>
          <Button size="small" onClick={() => setPickOpen(true)}>+ 拉人/AI</Button>
          {isOwner && (
            <Popconfirm title="解散该讨论群？聊天记录会存入知识库。" okText="解散" okButtonProps={{ danger: true }}
              onConfirm={async () => { await disbandChannel(channelId); message.success('已解散'); onDisband() }}>
              <Button size="small" danger>解散群</Button>
            </Popconfirm>
          )}
        </Space>
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
              {(m.attachments ?? []).map((att, i) => (
                <div key={i} style={{ marginTop: 4 }}>
                  {att.type === 'image' ? (
                    <img
                      src={`/api/v1/channels/attachments/download?storage_path=${encodeURIComponent(att.storage_path)}&name=${encodeURIComponent(att.name)}`}
                      alt={att.name} style={{ maxWidth: 180, maxHeight: 180, borderRadius: 6, cursor: 'pointer' }}
                      onClick={() => void downloadAttachment(att)}
                    />
                  ) : (
                    <a onClick={() => void downloadAttachment(att)} style={{ fontSize: 12 }}>
                      <PaperClipOutlined /> {att.name}
                    </a>
                  )}
                </div>
              ))}
            </div>
          )
        })}
        {sending && <div style={{ textAlign: 'center', margin: 8 }}><Spin size="small" /></div>}
      </div>
      {pending.length > 0 && (
        <div style={{ marginBottom: 6, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {pending.map((att, i) => (
            <Tag key={i} closable onClose={() => setPending((p) => p.filter((_, j) => j !== i))}>
              <PaperClipOutlined /> {att.name}
            </Tag>
          ))}
        </div>
      )}
      <Space.Compact style={{ width: '100%' }}>
        <Select
          mode="multiple" allowClear style={{ minWidth: 150 }}
          placeholder="@成员（真人/AI）" value={mentions} onChange={setMentions}
          optionFilterProp="label"
          options={members.map((m) => ({
            value: m.member_id,
            label: `${m.member_type === 'ai' ? '🤖' : '👤'} ${m.member_name || '（未命名）'}`,
          }))}
        />
        <Upload beforeUpload={onUpload} showUploadList={false} multiple>
          <Button icon={<PaperClipOutlined />} loading={uploading} title="发图片/文件" />
        </Upload>
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
          onMembershipChange()
          void listMembers(channelId).then(setMembers)
        }}
      />

      {/* 成员名单：群主可踢人 */}
      <Modal open={membersOpen} onCancel={() => setMembersOpen(false)} footer={null} title="群成员">
        {members.map((m) => {
          const isTheOwner = m.member_type === 'human' && m.member_id === ownerId
          return (
            <div key={`${m.member_type}-${m.member_id}`} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderTop: '1px solid #f0f0f0' }}>
              <Space>
                <span>{m.member_type === 'ai' ? '🤖' : '👤'}</span>
                <span>{m.member_name || '（未命名）'}</span>
                {isTheOwner && <Tag color="gold">群主</Tag>}
              </Space>
              {isOwner && !isTheOwner && (
                <Popconfirm title={`把「${m.member_name || '该成员'}」踢出群？`}
                  onConfirm={async () => {
                    await removeMember(channelId, m.member_type, m.member_id)
                    message.success('已踢出')
                    onMembershipChange()
                    void listMembers(channelId).then(setMembers)
                  }}>
                  <a style={{ color: '#cf1322' }}>踢出</a>
                </Popconfirm>
              )}
            </div>
          )
        })}
      </Modal>
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

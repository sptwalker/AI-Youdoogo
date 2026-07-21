/** 工作桌面对话区：统一承载我的助理、讨论组、未读数和实时消息订阅。 */
import { Badge, Card, Input, Modal, Select, message } from 'antd'
import { useCallback, useEffect, useRef, useState, type ComponentProps } from 'react'
import { roster, type Colleague } from '../../api/auth'
import { listRoles, type AgentRole } from '../../api/agents'
import {
  createChannel,
  myChannels,
  subscribeRealtime,
  type ChannelWithUnread,
  type Message as ChanMessage,
} from '../../api/discussion'
import GroupChat from '../GroupChat'
import AssistantChatCard from './AssistantChatCard'

type AssistantChatProps = ComponentProps<typeof AssistantChatCard>

export default function DesktopConversations({
  meId,
  assistant,
}: {
  meId?: string
  assistant: AssistantChatProps
}) {
  const [channels, setChannels] = useState<ChannelWithUnread[]>([])
  const [active, setActive] = useState<{ type: 'assistant' } | { type: 'group'; id: string; name: string }>({ type: 'assistant' })
  const [liveMessage, setLiveMessage] = useState<(ChanMessage & { channel_id?: string }) | null>(null)
  const [newGroupOpen, setNewGroupOpen] = useState(false)
  const [newGroupName, setNewGroupName] = useState('')
  const [newGroupAis, setNewGroupAis] = useState<string[]>([])
  const [newGroupHumans, setNewGroupHumans] = useState<string[]>([])
  const [agents, setAgents] = useState<AgentRole[]>([])
  const [users, setUsers] = useState<Colleague[]>([])
  const [creating, setCreating] = useState(false)
  const [realtimeConnected, setRealtimeConnected] = useState(false)
  const activeChannelIdRef = useRef<string | null>(null)
  const channelSignatureRef = useRef<string | null>(null)
  const subscriptionRef = useRef<ReturnType<typeof subscribeRealtime> | null>(null)

  activeChannelIdRef.current = active.type === 'group' ? active.id : null

  const loadChannels = useCallback(async (signal?: AbortSignal, forceResubscribe = false) => {
    const items = await myChannels({ signal, silent: true })
    if (signal?.aborted) return
    const signature = items.map((item) => item.id).sort().join(',')
    const previousSignature = channelSignatureRef.current
    channelSignatureRef.current = signature
    setChannels(items)
    setActive((current) => (
      current.type === 'group' && !items.some((item) => item.id === current.id)
        ? { type: 'assistant' }
        : current
    ))
    if (forceResubscribe || (previousSignature !== null && previousSignature !== signature)) {
      subscriptionRef.current?.restart()
    }
  }, [])

  useEffect(() => {
    let disposed = false
    void listRoles().then((items) => { if (!disposed) setAgents(items) }).catch(() => {})
    void roster().then((items) => { if (!disposed) setUsers(items) }).catch(() => {})
    return () => { disposed = true }
  }, [])

  useEffect(() => {
    const subscription = subscribeRealtime((event, data) => {
      if (event !== 'message') return
      const incoming = data as unknown as ChanMessage & { channel_id?: string }
      setLiveMessage(incoming)
      const activeId = activeChannelIdRef.current
      if (incoming.channel_id && incoming.channel_id !== activeId) {
        setChannels((items) => items.map((channel) => (
          channel.id === incoming.channel_id
            ? { ...channel, unread: (channel.unread ?? 0) + 1 }
            : channel
        )))
      }
    }, (state) => {
      setRealtimeConnected(state === 'connected')
    })
    subscriptionRef.current = subscription
    return () => {
      if (subscriptionRef.current === subscription) subscriptionRef.current = null
      subscription()
    }
  }, [])

  // Redis/SSE 故障时高频轮询；健康时保留低频群列表刷新，以发现“被拉入新群”。
  useEffect(() => {
    const ctrl = new AbortController()
    const intervalMs = realtimeConnected ? 60000 : 5000
    let timer: number | undefined
    let disposed = false
    const poll = async () => {
      try {
        await loadChannels(ctrl.signal)
      } catch { /* 静默降级，下一轮继续 */ }
      if (!disposed) timer = window.setTimeout(() => { void poll() }, intervalMs)
    }
    void poll()
    return () => {
      disposed = true
      ctrl.abort()
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [loadChannels, realtimeConnected])

  const createDiscussion = async () => {
    const name = newGroupName.trim()
    if (!name) {
      message.warning('请输入群名')
      return
    }
    const members = [
      ...newGroupHumans.map((id) => {
        const user = users.find((item) => item.id === id)
        return { member_type: 'human' as const, member_id: id, member_name: user?.real_name || user?.username }
      }),
      ...newGroupAis.map((id) => ({
        member_type: 'ai' as const,
        member_id: id,
        member_name: agents.find((item) => item.id === id)?.name,
      })),
    ]
    setCreating(true)
    try {
      const channel = await createChannel({ name, members })
      message.success('讨论组已创建')
      setNewGroupName('')
      setNewGroupHumans([])
      setNewGroupAis([])
      setNewGroupOpen(false)
      setActive({ type: 'group', id: channel.id, name: channel.name })
      try {
        await loadChannels(undefined, true)
      } catch {
        // 群已创建但列表刷新暂时失败时，也要立刻让服务端重取订阅集合。
        subscriptionRef.current?.restart()
      }
    } finally {
      setCreating(false)
    }
  }

  const activeChannel = active.type === 'group' ? channels.find((item) => item.id === active.id) : undefined
  const handleRead = useCallback((channelId: string) => {
    setChannels((items) => items.map((item) => item.id === channelId ? { ...item, unread: 0 } : item))
  }, [])

  return (
    <div style={{ flex: 1, minHeight: 0, minWidth: 0, display: 'flex', gap: 12, marginTop: 16 }}>
      <Card
        size="small"
        title="对话"
        style={{ width: 152, flexShrink: 0, overflowY: 'auto' }}
        styles={{ body: { padding: 6 } }}
        extra={<a style={{ fontSize: 12 }} onClick={() => setNewGroupOpen(true)}>+群</a>}
      >
        <div
          onClick={() => setActive({ type: 'assistant' })}
          style={{ cursor: 'pointer', padding: '6px', borderRadius: 4, fontSize: 12, background: active.type === 'assistant' ? '#e6f4ff' : undefined }}
        >
          💬 我的助理
        </div>
        {channels.map((channel) => {
          const selected = active.type === 'group' && active.id === channel.id
          return (
            <div
              key={channel.id}
              onClick={() => setActive({ type: 'group', id: channel.id, name: channel.name })}
              style={{ cursor: 'pointer', padding: '6px', borderRadius: 4, fontSize: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: selected ? '#e6f4ff' : undefined }}
            >
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}># {channel.name}</span>
              {channel.unread > 0 && !selected && <Badge count={channel.unread} size="small" />}
            </div>
          )
        })}
      </Card>

      <div style={{ flex: 1, minHeight: 0, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        {active.type === 'group' ? (
          <GroupChat
            channelId={active.id}
            channelName={active.name}
            liveMessage={liveMessage}
            onRead={handleRead}
            realtimeConnected={realtimeConnected}
            isOwner={activeChannel?.creator_id === meId}
            ownerId={activeChannel?.creator_id ?? null}
            onMembershipChange={() => { void loadChannels(undefined, true).catch(() => {}) }}
            onDisband={() => {
              setActive({ type: 'assistant' })
              void loadChannels(undefined, true).catch(() => {})
            }}
          />
        ) : (
          <AssistantChatCard {...assistant} />
        )}
      </div>

      <Modal
        open={newGroupOpen}
        title="新建讨论组"
        okText="创建"
        confirmLoading={creating}
        onCancel={() => setNewGroupOpen(false)}
        onOk={() => void createDiscussion()}
        destroyOnHidden
      >
        <Input placeholder="群名称" value={newGroupName} onChange={(event) => setNewGroupName(event.target.value)} style={{ marginBottom: 12 }} />
        <div style={{ marginBottom: 4, fontSize: 13 }}>拉真人员工</div>
        <Select
          mode="multiple"
          allowClear
          style={{ width: '100%', marginBottom: 12 }}
          placeholder="选择同事"
          value={newGroupHumans}
          onChange={setNewGroupHumans}
          optionFilterProp="label"
          options={users.map((user) => ({ value: user.id, label: user.real_name || user.username }))}
        />
        <div style={{ marginBottom: 4, fontSize: 13 }}>拉 AI 员工</div>
        <Select
          mode="multiple"
          allowClear
          style={{ width: '100%' }}
          placeholder="选择 AI"
          value={newGroupAis}
          onChange={setNewGroupAis}
          optionFilterProp="label"
          options={agents.map((agent) => ({ value: agent.id, label: agent.name }))}
        />
      </Modal>
    </div>
  )
}

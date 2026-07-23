import {
  Avatar,
  Badge,
  Button,
  Card,
  Empty,
  Input,
  List,
  Popconfirm,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from 'antd'
import { useEffect, useState } from 'react'
import Markdown from '../../components/Markdown'
import {
  discussionWorkspaceApi,
  type AgentRole,
  type ChannelWithUnread,
  type Message,
} from './api'
import { useAdvisorComposer } from './hooks/useAdvisorComposer'
import { useDiscussionFeed, type ChannelMessageSession } from './hooks/useDiscussionFeed'

export default function DiscussionWorkspace() {
  const [current, setCurrent] = useState<ChannelWithUnread | null>(null)
  const [agents, setAgents] = useState<AgentRole[]>([])
  const discussion = useDiscussionFeed({ activeChannelId: current?.id ?? null })

  useEffect(() => {
    let disposed = false
    void discussionWorkspaceApi.listAgents()
      .then((items) => { if (!disposed) setAgents(items) })
      .catch(() => {})
    return () => { disposed = true }
  }, [])

  useEffect(() => {
    setCurrent((selected) => {
      if (selected) {
        const updated = discussion.channels.find((channel) => channel.id === selected.id)
        if (updated) return updated
      }
      return discussion.channels[0] ?? null
    })
  }, [discussion.channels])

  return (
    <div style={{ display: 'flex', gap: 16 }}>
      <Card
        title="频道"
        size="small"
        style={{ width: 220, flexShrink: 0 }}
        styles={{ body: { padding: 8 } }}
      >
        <List
          size="small"
          dataSource={discussion.channels}
          locale={{ emptyText: '暂无频道' }}
          renderItem={(channel) => (
            <List.Item
              onClick={() => setCurrent(channel)}
              style={{
                cursor: 'pointer',
                padding: '6px 8px',
                borderRadius: 6,
                background: current?.id === channel.id ? '#e6f4ff' : undefined,
                display: 'flex',
                justifyContent: 'space-between',
              }}
            >
              <span>
                # {channel.name}
                {channel.is_archived && <Tag style={{ marginLeft: 4 }}>已归档</Tag>}
              </span>
              {channel.unread > 0 && current?.id !== channel.id && (
                <Badge count={channel.unread} size="small" />
              )}
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
          <AdvisorChannel
            key={current.id}
            channel={current}
            agents={agents}
            session={discussion.activeSession}
          />
        )}
      </Card>
    </div>
  )
}

function AdvisorChannel({
  channel,
  agents,
  session,
}: {
  channel: ChannelWithUnread
  agents: AgentRole[]
  session: ChannelMessageSession
}) {
  const composer = useAdvisorComposer({
    channelId: channel.id,
    ingestStreamEvent: session.ingestStreamEvent,
    clearStreamingMessage: session.clearStreamingMessage,
  })

  const promote = async (item: Message, target: 'proposal' | 'task') => {
    await discussionWorkspaceApi.promoteMessage(item.id, target)
    message.success(target === 'proposal' ? '已升格为提案' : '已升格为任务卡')
    session.refresh()
  }

  return (
    <>
      <div style={{ maxHeight: '55vh', overflowY: 'auto', marginBottom: 12 }}>
        <List
          dataSource={session.messages}
          locale={{ emptyText: '还没有消息，@ 一位顾问开始讨论' }}
          renderItem={(item) => (
            <List.Item
              actions={item.speaker_type === 'human' && !item.ref_id
                ? [
                    <Popconfirm
                      key="proposal"
                      title="把这条讨论升格为提案？"
                      onConfirm={() => promote(item, 'proposal')}
                    >
                      <a>升提案</a>
                    </Popconfirm>,
                    <Popconfirm
                      key="task"
                      title="把这条讨论升格为任务卡？"
                      onConfirm={() => promote(item, 'task')}
                    >
                      <a>升任务</a>
                    </Popconfirm>,
                  ]
                : undefined}
            >
              <List.Item.Meta
                avatar={
                  <Avatar style={{ background: item.speaker_type === 'ai' ? '#722ed1' : '#1677ff' }}>
                    {item.speaker_type === 'ai' ? 'AI' : item.speaker_name.slice(0, 1) || '人'}
                  </Avatar>
                }
                title={
                  <Space>
                    {item.speaker_name}
                    {item.speaker_type === 'ai' && <Tag color="purple">AI 顾问 · 参考</Tag>}
                    {item.ref_type && (
                      <Tag color="green">
                        已升{item.ref_type === 'proposal' ? '提案' : '任务'}
                      </Tag>
                    )}
                  </Space>
                }
                description={
                  <Typography.Paragraph style={{ marginBottom: 0 }}>
                    <Markdown>{item.content}</Markdown>
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
          value={composer.mentions}
          onChange={composer.setMentions}
          options={agents.map((agent) => ({ value: agent.id, label: agent.name }))}
        />
        <Input
          placeholder="输入消息，@顾问可触发一次参考意见…"
          value={composer.text}
          onChange={(event) => composer.setText(event.target.value)}
          onPressEnter={() => { void composer.send() }}
        />
        <Button
          type="primary"
          loading={composer.sending}
          onClick={() => { void composer.send() }}
        >
          发送
        </Button>
      </Space.Compact>
    </>
  )
}

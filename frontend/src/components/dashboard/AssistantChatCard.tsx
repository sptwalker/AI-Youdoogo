import { Button, Card, Input, List, Select, Space, Spin, Tag, Typography } from 'antd'
import type { Dispatch, RefObject, SetStateAction } from 'react'
import type { AddableAgent, DesktopMessage } from '../../api/desktop'
import type { OrchProgress } from '../../api/tasks'
import Markdown from '../Markdown'

export default function AssistantChatCard(props: {
  addable: AddableAgent[]
  addAgentIds: string[]
  assistant: { id: string; name: string } | null
  chatBoxRef: RefObject<HTMLDivElement | null>
  chatInput: string
  chatMessages: DesktopMessage[]
  chatSending: boolean
  orchestration: OrchProgress | null
  onAcceptStep: (stepId: string) => Promise<void>
  onSend: () => Promise<void>
  setAddAgentIds: Dispatch<SetStateAction<string[]>>
  setChatInput: Dispatch<SetStateAction<string>>
  setOrchestration: Dispatch<SetStateAction<OrchProgress | null>>
}) {
  const {
    addable,
    addAgentIds,
    assistant,
    chatBoxRef,
    chatInput,
    chatMessages,
    chatSending,
    orchestration,
    onAcceptStep,
    onSend,
    setAddAgentIds,
    setChatInput,
    setOrchestration,
  } = props

  return (
    <Card
      title={assistant ? `与${assistant.name}对话` : '我的助理'}
      style={{ marginTop: 16, flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}
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
          options={addable.map((agent) => ({ value: agent.id, label: agent.name }))}
        />
      }
    >
      <div
        ref={chatBoxRef}
        style={{ flex: 1, minHeight: 200, overflowY: 'auto', padding: '4px 2px', background: '#fafafa', borderRadius: 6, marginBottom: 10, fontSize: 12 }}
      >
        {chatMessages.length === 0 && (
          <Typography.Text type="secondary" style={{ display: 'block', textAlign: 'center', marginTop: 120 }}>
            向你的助理提问，它会结合知识库与过往对话回答（仅供参考）。可加入其他 AI 一起圆桌讨论。
          </Typography.Text>
        )}
        {chatMessages.map((chatMessage) => {
          const mine = chatMessage.speaker_type === 'user'
          return (
            <div key={chatMessage.id} style={{ textAlign: mine ? 'right' : 'left', margin: '10px 6px' }}>
              {!mine && <div style={{ fontSize: 12, color: '#888', marginBottom: 2 }}>{chatMessage.speaker_name}</div>}
              <span
                style={{
                  display: 'inline-block', maxWidth: '82%', padding: '7px 11px', borderRadius: 8,
                  textAlign: 'left', whiteSpace: mine ? 'pre-wrap' : 'normal',
                  background: mine ? '#1677ff' : '#fff', color: mine ? '#fff' : undefined,
                  border: mine ? undefined : '1px solid #eee',
                }}
              >
                {mine ? chatMessage.content : <Markdown>{chatMessage.content}</Markdown>}
              </span>
            </div>
          )
        })}
        {chatSending && <div style={{ textAlign: 'center', margin: 8 }}><Spin size="small" /></div>}
      </div>

      {orchestration && (
        <Card
          size="small"
          style={{ marginBottom: 10, background: '#f6ffed' }}
          title={
            <span style={{ fontSize: 12 }}>
              任务进度 {orchestration.accepted}/{orchestration.total}
              {orchestration.done && <Tag color="green" style={{ marginLeft: 8 }}>已完成</Tag>}
              {orchestration.awaiting_human.length > 0 && <Tag color="orange" style={{ marginLeft: 8 }}>待验收</Tag>}
            </span>
          }
          extra={<a style={{ fontSize: 12 }} onClick={() => setOrchestration(null)}>收起</a>}
        >
          <List
            size="small"
            dataSource={orchestration.steps}
            renderItem={(step) => {
              const icon = step.status === 'accepted' ? '✅' : step.status === 'reported' ? '⏸' : step.status === 'executing' ? '▶' : '○'
              const waiting = step.red_line && step.status === 'reported'
              return (
                <List.Item
                  style={{ fontSize: 12, padding: '4px 0' }}
                  actions={waiting ? [<a key="ac" onClick={() => void onAcceptStep(step.id)}>验收并继续</a>] : []}
                >
                  <Space size={6}>
                    <span>{icon}</span>
                    <span>步骤{step.step_no + 1}·{step.title}</span>
                    <Tag>{step.skill}</Tag>
                    {step.red_line && <Tag color="red">红线</Tag>}
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
          onChange={(event) => setChatInput(event.target.value)}
          onPressEnter={() => void onSend()}
        />
        <Button type="primary" loading={chatSending} onClick={() => void onSend()}>发送</Button>
      </Space.Compact>
    </Card>
  )
}

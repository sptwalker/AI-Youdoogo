import { Input, Modal, Select, message } from 'antd'
import { useState } from 'react'
import type { AgentRole, Colleague, MemberToAdd } from '../api'
import { buildCreateDiscussionRequest } from '../workspaceModel'

interface NewDiscussionModalProps {
  open: boolean
  creating: boolean
  agents: AgentRole[]
  colleagues: Colleague[]
  onClose(): void
  onCreate(request: {
    name: string
    members: MemberToAdd[]
  }): Promise<void>
}

export function NewDiscussionModal({
  open,
  creating,
  agents,
  colleagues,
  onClose,
  onCreate,
}: NewDiscussionModalProps) {
  const [name, setName] = useState('')
  const [selectedAgents, setSelectedAgents] = useState<string[]>([])
  const [selectedHumans, setSelectedHumans] = useState<string[]>([])

  const submit = async () => {
    const request = buildCreateDiscussionRequest({
      name,
      humanIds: selectedHumans,
      agentIds: selectedAgents,
      colleagues,
      agents,
    })
    if (!request) {
      message.warning('请输入群名')
      return
    }
    await onCreate(request)
    setName('')
    setSelectedHumans([])
    setSelectedAgents([])
  }

  return (
    <Modal
      open={open}
      title="新建讨论组"
      okText="创建"
      confirmLoading={creating}
      onCancel={onClose}
      onOk={submit}
      destroyOnHidden
    >
      <Input
        placeholder="群名称"
        value={name}
        onChange={(event) => setName(event.target.value)}
        style={{ marginBottom: 12 }}
      />
      <div style={{ marginBottom: 4, fontSize: 13 }}>拉真人员工</div>
      <Select
        mode="multiple"
        allowClear
        style={{ width: '100%', marginBottom: 12 }}
        placeholder="选择同事"
        value={selectedHumans}
        onChange={setSelectedHumans}
        optionFilterProp="label"
        options={colleagues.map((colleague) => ({
          value: colleague.id,
          label: colleague.real_name || colleague.username,
        }))}
      />
      <div style={{ marginBottom: 4, fontSize: 13 }}>拉 AI 员工</div>
      <Select
        mode="multiple"
        allowClear
        style={{ width: '100%' }}
        placeholder="选择 AI"
        value={selectedAgents}
        onChange={setSelectedAgents}
        optionFilterProp="label"
        options={agents.map((agent) => ({ value: agent.id, label: agent.name }))}
      />
    </Modal>
  )
}

import { Avatar, Modal, Select, Typography } from 'antd'
import { useEffect, useState } from 'react'
import type { AgentRole, Colleague, MemberToAdd } from '../api'
import { buildMembersToAdd } from '../model'

interface MemberPickerProps {
  open: boolean
  existing: string[]
  agents: AgentRole[]
  colleagues: Colleague[]
  onOpen(): void
  onClose(): void
  onAdd(members: MemberToAdd[]): Promise<void>
}

export function MemberPicker({
  open,
  existing,
  agents,
  colleagues,
  onOpen,
  onClose,
  onAdd,
}: MemberPickerProps) {
  const [selectedHumans, setSelectedHumans] = useState<string[]>([])
  const [selectedAgents, setSelectedAgents] = useState<string[]>([])

  useEffect(() => {
    if (open) onOpen()
  }, [onOpen, open])

  const submit = async () => {
    const members = buildMembersToAdd(selectedHumans, selectedAgents, colleagues, agents)
    if (members.length > 0) await onAdd(members)
    setSelectedHumans([])
    setSelectedAgents([])
  }

  return (
    <Modal
      open={open}
      onCancel={onClose}
      onOk={submit}
      title="拉人 / AI 进群"
      okText="拉入"
    >
      <div style={{ marginBottom: 12 }}>
        <div style={{ marginBottom: 4 }}>真人员工</div>
        <Select
          mode="multiple"
          allowClear
          style={{ width: '100%' }}
          placeholder="选择同事"
          value={selectedHumans}
          onChange={setSelectedHumans}
          optionFilterProp="label"
          options={colleagues
            .filter((colleague) => !existing.includes(colleague.id))
            .map((colleague) => ({
              value: colleague.id,
              label: colleague.real_name || colleague.username,
            }))}
        />
      </div>
      <div>
        <div style={{ marginBottom: 4 }}>AI 员工</div>
        <Select
          mode="multiple"
          allowClear
          style={{ width: '100%' }}
          placeholder="选择 AI"
          value={selectedAgents}
          onChange={setSelectedAgents}
          optionFilterProp="label"
          options={agents
            .filter((agent) => !existing.includes(agent.id))
            .map((agent) => ({ value: agent.id, label: agent.name }))}
        />
      </div>
      <Typography.Text
        type="secondary"
        style={{ fontSize: 12, display: 'block', marginTop: 8 }}
      >
        <Avatar size={14} style={{ marginRight: 4 }} />
        真人需先登录过本系统才可被拉入。
      </Typography.Text>
    </Modal>
  )
}

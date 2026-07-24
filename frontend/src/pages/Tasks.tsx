/** 任务卡：创建 / 列表 / 调度执行 / 状态流转（验收由真人确认）。 */
import {
  ModalForm,
  PageContainer,
  ProFormDigit,
  ProFormSelect,
  ProFormText,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components'
import { Button, Space, Tag, Typography, message } from 'antd'
import { useRef } from 'react'
import Markdown from '../components/Markdown'
import { listRoles } from '../api/agents'
import {
  createTask,
  listTasks,
  runTask,
  STATUS_LABEL,
  transitionTask,
  type TaskCard,
} from '../api/tasks'
import { taskHumanActions } from '../features/tasks/model'
import { usePendingActions } from '../hooks/usePendingActions'

const STATUS_COLOR: Record<string, string> = {
  created: 'default',
  dispatched: 'blue',
  executing: 'processing',
  reported: 'gold',
  accepted: 'success',
  rejected: 'error',
  cancelled: 'default',
}

async function agentRoleOptions() {
  const roles = await listRoles()
  return roles.map((r) => ({ label: r.name, value: r.id }))
}

export default function Tasks() {
  const actionRef = useRef<ActionType>(null)
  const pending = usePendingActions()
  const reload = () => actionRef.current?.reload()

  const columns: ProColumns<TaskCard>[] = [
    { title: '标题', dataIndex: 'title' },
    { title: '类型', dataIndex: 'task_type' },
    { title: '优先级', dataIndex: 'priority' },
    {
      title: '状态',
      dataIndex: 'status',
      valueEnum: Object.fromEntries(
        Object.entries(STATUS_LABEL).map(([k, v]) => [k, { text: v }]),
      ),
      render: (_, r) => <Tag color={STATUS_COLOR[r.status]}>{STATUS_LABEL[r.status] || r.status}</Tag>,
    },
    { title: '创建时间', dataIndex: 'create_time', valueType: 'dateTime', search: false },
    {
      title: '操作',
      valueType: 'option',
      render: (_, r) => {
        const actions = []
        if (r.assignee_agent_id && (r.status === 'created' || r.status === 'dispatched')) {
          const runKey = `run:${r.id}`
          actions.push(
            <Button
              key="run"
              type="link"
              size="small"
              loading={pending.isPending(runKey)}
              onClick={() => {
                void pending.run(runKey, async () => {
                  await runTask(r.id)
                  message.success('已调度执行')
                  reload()
                }).catch(() => {})
              }}
            >
              运行
            </Button>,
          )
        }
        for (const action of taskHumanActions(r.status)) {
          const transitionKey = `transition:${r.id}:${action.to}`
          actions.push(
            <Button
              key={action.to}
              type="link"
              size="small"
              danger={action.danger}
              loading={pending.isPending(transitionKey)}
              onClick={() => {
                void pending.run(transitionKey, async () => {
                  await transitionTask(r.id, action.to)
                  message.success(`已${action.label}`)
                  reload()
                }).catch(() => {})
              }}
            >
              {action.label}
            </Button>,
          )
        }
        return actions.length ? actions : '-'
      },
    },
  ]

  return (
    <PageContainer title="任务卡">
      <ProTable<TaskCard>
        rowKey="id"
        actionRef={actionRef}
        columns={columns}
        request={async (params) => ({
          data: await listTasks(params.status as string | undefined),
          success: true,
        })}
        expandable={{
          expandedRowRender: (r) => (
            <Space direction="vertical">
              {r.assignee_agent_id && <span>指派智能体：{r.assignee_agent_id}</span>}
              <Typography.Paragraph style={{ margin: 0 }}>
                <Markdown>{r.result_content || '（暂无执行结果）'}</Markdown>
              </Typography.Paragraph>
            </Space>
          ),
        }}
        toolBarRender={() => [
          <ModalForm<{
            title: string
            task_type: string
            priority: string
            assignee_agent_id?: string
            sla_hours?: number
          }>
            key="create"
            title="创建任务卡"
            trigger={<Button type="primary">新建任务</Button>}
            modalProps={{ destroyOnHidden: true }}
            onFinish={async (v) => {
              await createTask(v)
              message.success('已创建')
              reload()
              return true
            }}
          >
            <ProFormText name="title" label="标题" rules={[{ required: true }]} />
            <ProFormText name="task_type" label="类型" rules={[{ required: true }]} />
            <ProFormSelect
              name="priority"
              label="优先级"
              initialValue="normal"
              options={[
                { value: 'high', label: '高' },
                { value: 'normal', label: '普通' },
                { value: 'low', label: '低' },
              ]}
            />
            <ProFormSelect
              name="assignee_agent_id"
              label="指派智能体（可选）"
              request={agentRoleOptions}
            />
            <ProFormDigit name="sla_hours" label="SLA(小时，可选)" min={1} />
          </ModalForm>,
        ]}
      />
    </PageContainer>
  )
}

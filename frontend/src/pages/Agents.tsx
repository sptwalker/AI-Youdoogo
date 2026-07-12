/** 智能体：角色一览 + 生成运营提案 + 执行留痕（可展开看全文）。 */
import {
  ModalForm,
  PageContainer,
  ProFormText,
  ProFormTextArea,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components'
import { Button, Card, Tag, Typography, message } from 'antd'
import { useRef } from 'react'
import {
  generateProposal,
  listRecords,
  listRoles,
  type AgentRole,
  type TaskRecord,
} from '../api/agents'

const TASK_LABEL: Record<string, string> = {
  daily_report: '运营日报',
  anomaly_alert: '异常告警',
  proposal: '运营提案',
}

export default function Agents() {
  const actionRef = useRef<ActionType>(null)

  const columns: ProColumns<TaskRecord>[] = [
    {
      title: '任务',
      dataIndex: 'task_type',
      render: (_, r) => TASK_LABEL[r.task_type] || r.task_type,
    },
    { title: '摘要', dataIndex: 'input_summary', render: (_, r) => r.input_summary || '-' },
    {
      title: '状态',
      dataIndex: 'status',
      render: (_, r) => (
        <Tag color={r.status === 'success' ? 'success' : 'error'}>
          {r.status === 'success' ? '成功' : '失败'}
        </Tag>
      ),
    },
    { title: '模型', dataIndex: 'model_used', render: (_, r) => r.model_used || '-' },
    { title: '耗时(ms)', dataIndex: 'duration_ms' },
    { title: '时间', dataIndex: 'create_time', valueType: 'dateTime' },
  ]

  return (
    <PageContainer title="智能体">
      <RolesCard />
      <ProTable<TaskRecord>
        rowKey="id"
        actionRef={actionRef}
        headerTitle="执行留痕（AI 产出仅供参考，需真人确认）"
        search={false}
        columns={columns}
        request={async () => ({ data: await listRecords(50), success: true })}
        expandable={{
          expandedRowRender: (r) => (
            <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
              {r.output_content || r.error_msg || '（无内容）'}
            </Typography.Paragraph>
          ),
        }}
        toolBarRender={() => [
          <ModalForm<{ topic: string; context?: string }>
            key="proposal"
            title="生成运营提案"
            trigger={<Button type="primary">生成提案</Button>}
            modalProps={{ destroyOnHidden: true }}
            onFinish={async (v) => {
              await generateProposal(v.topic, v.context ?? '')
              message.success('已生成，见留痕列表')
              actionRef.current?.reload()
              return true
            }}
          >
            <ProFormText name="topic" label="议题" rules={[{ required: true }]} />
            <ProFormTextArea name="context" label="参考信息（可选）" />
          </ModalForm>,
        ]}
      />
    </PageContainer>
  )
}

function RolesCard() {
  return (
    <Card title="智能体角色" style={{ marginBottom: 16 }}>
      <ProTable<AgentRole>
        rowKey="id"
        search={false}
        options={false}
        pagination={false}
        request={async () => ({ data: await listRoles(), success: true })}
        columns={[
          { title: '角色', dataIndex: 'name' },
          { title: '职责', dataIndex: 'duty', render: (_, r) => r.duty || '-' },
          { title: '模型档位', dataIndex: 'model_role' },
          {
            title: '启用',
            dataIndex: 'is_active',
            render: (_, r) => <Tag color={r.is_active ? 'success' : 'default'}>
              {r.is_active ? '启用' : '停用'}
            </Tag>,
          },
        ]}
      />
    </Card>
  )
}

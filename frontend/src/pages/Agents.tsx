/** 智能体：角色一览(+提示词优化) + 生成运营提案 + 执行留痕(可展开·可评分)。 */
import {
  ModalForm,
  PageContainer,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components'
import { Button, Card, Modal, Rate, Space, Tag, Typography, message } from 'antd'
import { useEffect, useRef, useState } from 'react'
import Markdown from '../components/Markdown'
import {
  addFeedback,
  generateProposal,
  listRecords,
  listRoles,
  listSkills,
  optimizePrompt,
  updateRolePrompt,
  updateRoleTools,
  type AgentRole,
  type OptimizeResult,
  type SkillInfo,
  type TaskRecord,
} from '../api/agents'

const TASK_LABEL: Record<string, string> = {
  daily_report: '运营日报',
  anomaly_alert: '异常告警',
  proposal: '运营提案',
  proposal_research: '提案预研',
  proposal_execution: '提案执行',
  meeting_discuss: '会议发言',
  meeting_minutes: '会议纪要',
  meeting_vote: 'AI参考票',
  analysis: '分析',
  resolution_execution: '决议执行',
}

export default function Agents() {
  const actionRef = useRef<ActionType>(null)

  const columns: ProColumns<TaskRecord>[] = [
    { title: '任务', dataIndex: 'task_type', render: (_, r) => TASK_LABEL[r.task_type] || r.task_type },
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
    {
      title: '评分',
      render: (_, r) => (
        <Rate
          onChange={async (v) => {
            await addFeedback(r.id, v)
            message.success('已评分，可在角色卡触发提示词优化')
          }}
        />
      ),
    },
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
            <Typography.Paragraph style={{ margin: 0 }}>
              <Markdown>{r.output_content || r.error_msg || '（无内容）'}</Markdown>
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
  const [opt, setOpt] = useState<OptimizeResult | null>(null)
  const [skillList, setSkillList] = useState<SkillInfo[]>([])
  const rolesRef = useRef<ActionType>(null)
  useEffect(() => {
    void listSkills().then(setSkillList)
  }, [])
  const skillLabel = (k: string) => skillList.find((s) => s.key === k)?.label ?? k

  return (
    <Card title="智能体角色" style={{ marginBottom: 16 }}>
      <ProTable<AgentRole>
        rowKey="id"
        actionRef={rolesRef}
        search={false}
        options={false}
        pagination={false}
        request={async () => ({ data: await listRoles(), success: true })}
        columns={[
          { title: '角色', dataIndex: 'name' },
          { title: '职责', dataIndex: 'duty', render: (_, r) => r.duty || '-' },
          { title: '模型档位', dataIndex: 'model_role' },
          {
            title: '技能',
            dataIndex: 'tools',
            render: (_, r) =>
              r.tools.length === 0 ? (
                <Tag>默认全开</Tag>
              ) : (
                <Space size={4} wrap>
                  {r.tools.map((k) => (
                    <Tag key={k} color="blue">{skillLabel(k)}</Tag>
                  ))}
                </Space>
              ),
          },
          {
            title: '启用',
            dataIndex: 'is_active',
            render: (_, r) => (
              <Tag color={r.is_active ? 'success' : 'default'}>{r.is_active ? '启用' : '停用'}</Tag>
            ),
          },
          {
            title: '操作',
            render: (_, r) => (
              <Space>
                <ModalForm<{ tools: string[] }>
                  key="skills"
                  title={`配置技能 · ${r.name}`}
                  trigger={<a>配置技能</a>}
                  modalProps={{ destroyOnHidden: true }}
                  initialValues={{ tools: r.tools }}
                  onFinish={async (v) => {
                    await updateRoleTools(r.id, v.tools ?? [])
                    message.success('已更新技能')
                    rolesRef.current?.reload()
                    return true
                  }}
                >
                  <ProFormSelect
                    name="tools"
                    label="启用技能"
                    mode="multiple"
                    tooltip="留空 = 默认技能全开"
                    options={skillList.map((s) => ({
                      value: s.key,
                      label: `${s.label}（${s.description}）`,
                    }))}
                  />
                </ModalForm>
                <a
                  onClick={async () => {
                    message.loading({ content: '基于低分反馈优化中…', key: 'o' })
                    try {
                      setOpt(await optimizePrompt(r.id))
                      message.destroy('o')
                    } catch {
                      message.destroy('o')
                    }
                  }}
                >
                  优化提示词
                </a>
              </Space>
            ),
          },
        ]}
      />
      <Modal
        open={opt !== null}
        onCancel={() => setOpt(null)}
        title="提示词优化建议（须真人确认应用）"
        width={720}
        okText="应用为新提示词"
        onOk={async () => {
          if (opt) {
            await updateRolePrompt(opt.role_id, opt.suggested_prompt)
            message.success('已应用')
            setOpt(null)
          }
        }}
      >
        {opt && (
          <>
            <Typography.Text type="secondary">
              基于 {opt.based_on_samples} 条低分反馈
            </Typography.Text>
            <Typography.Title level={5}>当前提示词</Typography.Title>
            <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
              {opt.current_prompt}
            </Typography.Paragraph>
            <Typography.Title level={5}>建议提示词</Typography.Title>
            <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
              {opt.suggested_prompt}
            </Typography.Paragraph>
          </>
        )}
      </Modal>
    </Card>
  )
}

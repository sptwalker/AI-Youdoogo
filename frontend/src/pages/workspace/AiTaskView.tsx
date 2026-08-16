/** AI 任务视图：NL 先出计划（DAG）→ 真人确认 → 执行 → 进度。
 *
 *  红线（docs/27 §十一）：对外/业务/资金/人事步骤在运行时停「待验收」，需真人逐步确认才继续；
 *  本页只呈现与触发，绝不放宽——红线步在预览即标红，执行后停在 awaiting_human 等真人「验收并继续」。 */
import { Alert, Button, Card, Input, List, Space, Tag, Typography, message } from 'antd'
import {
  CheckCircleTwoTone,
  MinusCircleOutlined,
  PauseCircleTwoTone,
  PlayCircleTwoTone,
} from '@ant-design/icons'
import { useEffect, useState } from 'react'
import { executeAiTask, planAiTask, type PlanPreview } from '../../api/aiTasks'
import { getOrchestrationProgress, transitionTask, type OrchProgress } from '../../api/tasks'

const NULL_PLAN_HINT: Record<string, string> = {
  single_action: '这更像单步任务，建议直接建普通任务卡。',
  insufficient_steps: '拆不出多步编排，建议直接建普通任务卡。',
  invalid_json: '计划解析失败，请换个说法重试。',
  invalid_step: '计划步骤不合法，请换个说法重试。',
}

// 与后端 work_planning.AUTOMATIC_CAPABILITIES 对齐：仅取数/交付/知识沉淀免真人停点，其余皆红线。
// 仅用于预览高亮；真正的停点强制在运行时逐步判定（前端放宽也停不了对外发送）。
const AUTOMATIC = new Set(['data_query', 'deliver', 'knowledge_index'])
const isRedLine = (capability: string) => !AUTOMATIC.has(capability)

export default function AiTaskView() {
  const [request, setRequest] = useState('')
  const [title, setTitle] = useState('')
  const [plan, setPlan] = useState<PlanPreview | null>(null)
  const [planning, setPlanning] = useState(false)
  const [executing, setExecuting] = useState(false)
  const [orch, setOrch] = useState<OrchProgress | null>(null)

  // 编排由租约 worker 异步驱动 → 未完成时轮询刷新进度（含红线停点导致的 awaiting_human）。
  useEffect(() => {
    if (!orch || orch.done) return
    const timer = setInterval(() => {
      void getOrchestrationProgress(orch.parent_id).then(setOrch).catch(() => undefined)
    }, 3000)
    return () => clearInterval(timer)
  }, [orch])

  const onPlan = async () => {
    setPlanning(true)
    setPlan(null)
    setOrch(null)
    try {
      const result = await planAiTask({ request: request.trim(), title: title.trim() || undefined })
      if (result.plan === null) {
        message.info(NULL_PLAN_HINT[result.reason ?? ''] ?? '未能生成多步计划。')
        return
      }
      setPlan(result.plan)
    } catch {
      /* 失败提示已由全局请求拦截统一弹出 */
    } finally {
      setPlanning(false)
    }
  }

  const onExecute = async () => {
    if (!plan) return
    setExecuting(true)
    try {
      setOrch(await executeAiTask({ request: plan.request, title: title.trim() || undefined, steps: plan.steps }))
      setPlan(null)
      message.success('已按计划启动编排')
    } catch {
      /* 失败提示已由全局请求拦截统一弹出 */
    } finally {
      setExecuting(false)
    }
  }

  const acceptStep = async (stepId: string) => {
    try {
      await transitionTask(stepId, 'accepted', '真人验收')
      if (orch) setOrch(await getOrchestrationProgress(orch.parent_id))
      message.success('已验收，继续后续步骤')
    } catch {
      /* 失败提示已由全局请求拦截统一弹出 */
    }
  }

  const hasRedLine = plan?.steps.some((step) => isRedLine(step.capability_key))

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card size="small" title="描述你的任务，AI 先出计划再由你确认执行">
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Input placeholder="标题（可选）" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} />
          <Input.TextArea
            placeholder="例如：拉取本月销售与财务数据，汇总成月度经营报告草稿"
            value={request}
            onChange={(e) => setRequest(e.target.value)}
            autoSize={{ minRows: 3, maxRows: 8 }}
            maxLength={4000}
          />
          <Button type="primary" loading={planning} disabled={request.trim().length < 8} onClick={() => void onPlan()}>
            生成计划
          </Button>
        </Space>
      </Card>

      {plan && (
        <Card
          size="small"
          title={`计划预览（${plan.steps.length} 步）— 请确认后执行`}
          extra={<Button type="primary" loading={executing} onClick={() => void onExecute()}>确认执行</Button>}
        >
          {hasRedLine && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              message="计划含对外/业务步骤（红线）"
              description="执行到红线步会停在「待验收」，需你逐步确认后才继续，AI 不会自行对外发送或改动业务。"
            />
          )}
          <List
            size="small"
            dataSource={plan.steps}
            renderItem={(step) => {
              const redLine = isRedLine(step.capability_key)
              return (
                <List.Item>
                  <Space size={6} wrap>
                    <span>步骤{step.number + 1}·{step.title}</span>
                    <Tag>{step.capability_key}</Tag>
                    {redLine && <Tag color="red">红线</Tag>}
                    {step.depends_on.length > 0 && (
                      <Typography.Text type="secondary">依赖 {step.depends_on.map((d) => `步骤${d + 1}`).join('、')}</Typography.Text>
                    )}
                  </Space>
                </List.Item>
              )
            }}
          />
        </Card>
      )}

      {orch && (
        <Card
          size="small"
          style={{ background: '#f6ffed' }}
          title={
            <Space>
              <span>执行进度 {orch.accepted}/{orch.total}</span>
              {orch.done && <Tag color="green">已完成</Tag>}
              {orch.awaiting_human.length > 0 && <Tag color="orange">待验收 {orch.awaiting_human.length}</Tag>}
            </Space>
          }
        >
          <List
            size="small"
            dataSource={orch.steps}
            renderItem={(step) => {
              const waiting = step.red_line && step.status === 'reported'
              const icon =
                step.status === 'accepted' ? (
                  <CheckCircleTwoTone twoToneColor="#52c41a" />
                ) : step.status === 'reported' ? (
                  <PauseCircleTwoTone twoToneColor="#fa8c16" />
                ) : step.status === 'executing' ? (
                  <PlayCircleTwoTone twoToneColor="#1677ff" />
                ) : (
                  <MinusCircleOutlined style={{ color: '#bfbfbf' }} />
                )
              return (
                <List.Item actions={waiting ? [<a key="accept" onClick={() => void acceptStep(step.id)}>验收并继续</a>] : []}>
                  <Space size={6} wrap>
                    <span aria-label={step.status}>{icon}</span>
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
    </Space>
  )
}

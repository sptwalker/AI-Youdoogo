import type { TaskStatus } from '../../api/tasks'

/** 任务类型的中文标签(列表展示 + 创建下拉共用,避免自由文本脏数据)。 */
export const TASK_TYPE_LABEL: Record<string, string> = {
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

export const TASK_TYPE_OPTIONS = Object.entries(TASK_TYPE_LABEL).map(([value, label]) => ({ value, label }))

export interface TaskHumanAction {
  to: TaskStatus
  label: string
  danger?: boolean
}

const HUMAN_ACTIONS: Partial<Record<TaskStatus, readonly TaskHumanAction[]>> = {
  reported: [
    { to: 'accepted', label: '验收' },
    { to: 'rejected', label: '驳回', danger: true },
  ],
  created: [{ to: 'cancelled', label: '终止', danger: true }],
  dispatched: [{ to: 'cancelled', label: '终止', danger: true }],
  executing: [{ to: 'cancelled', label: '终止', danger: true }],
  rejected: [
    { to: 'dispatched', label: '重新分发' },
    { to: 'cancelled', label: '终止', danger: true },
  ],
}

export function taskHumanActions(status: TaskStatus): readonly TaskHumanAction[] {
  return HUMAN_ACTIONS[status] ?? []
}

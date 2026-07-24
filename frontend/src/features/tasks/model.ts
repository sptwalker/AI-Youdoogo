import type { TaskStatus } from '../../api/tasks'

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

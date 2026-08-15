import type { TaskCard } from '../../api/tasks'

/** 看板泳道（与后端 domain/board.py 的中文 lane 值对齐）。
 *  主泳道恒显；驳回/已终止/已归档仅在有卡时追加，避免空列占屏。 */
export const PRIMARY_LANES = ['待启动', '进行中', '待审核', '已完成'] as const
export const EXTRA_LANES = ['驳回', '已终止', '已归档'] as const

export const LANE_COLOR: Record<string, string> = {
  待启动: 'default',
  进行中: 'processing',
  待审核: 'gold',
  已完成: 'success',
  驳回: 'error',
  已终止: 'default',
  已归档: 'default',
}

/** 按泳道分组，保留输入顺序（后端已按优先级/时间排好）。 */
export function groupByLane(tasks: TaskCard[]): Record<string, TaskCard[]> {
  const groups: Record<string, TaskCard[]> = {}
  for (const task of tasks) {
    ;(groups[task.lane] ??= []).push(task)
  }
  return groups
}

/** 要渲染的泳道列：主泳道 + 有卡的附加泳道。 */
export function laneColumns(tasks: TaskCard[]): string[] {
  const present = new Set(tasks.map((t) => t.lane))
  return [...PRIMARY_LANES, ...EXTRA_LANES.filter((lane) => present.has(lane))]
}

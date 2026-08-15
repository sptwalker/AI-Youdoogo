import { describe, expect, it } from 'vitest'
import type { TaskCard } from '../../api/tasks'
import { PRIMARY_LANES, groupByLane, laneColumns } from './board'

function task(overrides: Partial<TaskCard> = {}): TaskCard {
  return {
    id: 'id',
    title: 't',
    task_type: 'manual',
    priority: 'normal',
    status: 'created',
    creator_id: 'u',
    assignee_agent_id: null,
    parent_id: null,
    sla_hours: null,
    result_content: null,
    create_time: '2026-08-15T00:00:00Z',
    project_id: null,
    archived_at: null,
    lane: '待启动',
    blocked: false,
    ...overrides,
  }
}

describe('workspace board grouping', () => {
  it('groups tasks by lane preserving input order', () => {
    const a = task({ id: 'a', lane: '进行中' })
    const b = task({ id: 'b', lane: '进行中' })
    const c = task({ id: 'c', lane: '待审核' })
    const groups = groupByLane([a, b, c])
    expect(groups['进行中'].map((t) => t.id)).toEqual(['a', 'b'])
    expect(groups['待审核'].map((t) => t.id)).toEqual(['c'])
  })

  it('always shows primary lanes and appends extra lanes only when present', () => {
    expect(laneColumns([task({ lane: '进行中' })])).toEqual([...PRIMARY_LANES])
    expect(laneColumns([task({ lane: '驳回' })])).toEqual([...PRIMARY_LANES, '驳回'])
    expect(laneColumns([task({ lane: '已归档' }), task({ lane: '驳回' })])).toEqual([
      ...PRIMARY_LANES,
      '驳回',
      '已归档',
    ])
  })
})

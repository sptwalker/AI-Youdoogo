import { describe, expect, it } from 'vitest'
import { taskHumanActions } from './model'

describe('task human actions', () => {
  it('keeps cancellation available for executing and rejected tasks', () => {
    expect(taskHumanActions('executing')).toContainEqual({
      to: 'cancelled', label: '终止', danger: true,
    })
    expect(taskHumanActions('rejected')).toEqual([
      { to: 'dispatched', label: '重新分发' },
      { to: 'cancelled', label: '终止', danger: true },
    ])
  })
})

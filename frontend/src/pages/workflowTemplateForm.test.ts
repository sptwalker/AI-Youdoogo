/** 工作流模板步骤纯校验单测（vitest 纯逻辑，镜像后端 validation.py 用例 + 行↔步转换）。 */
import { describe, expect, it } from 'vitest'
import type { WorkflowStep } from '../api/workflowTemplates'
import { rowsToSteps, stepsToRows, validateSteps, type StepRow } from './workflowTemplateForm'

const step = (no: number, extra: Partial<WorkflowStep> = {}): WorkflowStep => ({
  no,
  title: `步骤${no}`,
  skill: 'data_query',
  instruction: '指令',
  depends_on: [],
  expert_code: null,
  ...extra,
})

describe('validateSteps', () => {
  it('接受合法 DAG', () => {
    expect(validateSteps([step(0), step(1), step(2, { depends_on: [0, 1] })])).toEqual([])
  })

  it('拒空模板', () => {
    expect(validateSteps([]).length).toBeGreaterThan(0)
  })

  it('拒重复 no', () => {
    expect(validateSteps([step(0), step(0)]).some((e) => e.includes('重复'))).toBe(true)
  })

  it('拒空标题/指令', () => {
    expect(validateSteps([step(0, { title: '  ' })]).some((e) => e.includes('标题'))).toBe(true)
    expect(validateSteps([step(0, { instruction: '' })]).some((e) => e.includes('指令'))).toBe(true)
  })

  it('拒自依赖', () => {
    expect(validateSteps([step(0, { depends_on: [0] })]).some((e) => e.includes('自身'))).toBe(true)
  })

  it('拒悬挂依赖', () => {
    expect(validateSteps([step(0, { depends_on: [9] })]).some((e) => e.includes('不存在'))).toBe(true)
  })

  it('拒成环（0→1→2→0）', () => {
    const cyclic = [
      step(0, { depends_on: [2] }),
      step(1, { depends_on: [0] }),
      step(2, { depends_on: [1] }),
    ]
    expect(validateSteps(cyclic).some((e) => e.includes('环'))).toBe(true)
  })
})

describe('stepsToRows / rowsToSteps 往返', () => {
  it('rowsToSteps 按行序赋 no，去自依赖，空 expert_code → null', () => {
    const rows: StepRow[] = [
      { title: 'A', skill: 'data_query', instruction: 'i', depends_on: [] },
      { title: 'B', skill: 'deliver', instruction: 'j', depends_on: [0, 1], expert_code: ' ' },
    ]
    const steps = rowsToSteps(rows)
    expect(steps.map((s) => s.no)).toEqual([0, 1])
    expect(steps[1].depends_on).toEqual([0]) // 去掉自依赖 1
    expect(steps[1].expert_code).toBeNull()
  })

  it('stepsToRows 把 depends_on 从 no 重映射为行下标（no 非连续）', () => {
    const rows = stepsToRows([step(5), step(9, { depends_on: [5] })])
    expect(rows[1].depends_on).toEqual([0]) // no=5 → 行下标 0
  })

  it('往返保持结构（合法 DAG）', () => {
    const original = [step(0), step(1, { skill: 'deliver', depends_on: [0] })]
    const round = rowsToSteps(stepsToRows(original))
    expect(validateSteps(round)).toEqual([])
    expect(round[1].depends_on).toEqual([0])
  })
})

/** 工作流模板步骤纯校验（镜像后端 validation.py，仅作即时 UX，后端仍是校验权威）。 */
import type { WorkflowStep } from '../api/workflowTemplates'

/** 返回错误信息数组（空 = 通过）。检查：非空 / no 唯一非负 / 标题指令非空 /
 *  depends_on 引用存在的 no、不自依赖 / 依赖无环（Kahn 拓扑）。skill 白名单由后端权威校验。 */
export function validateSteps(steps: WorkflowStep[]): string[] {
  const errors: string[] = []
  if (steps.length === 0) return ['模板至少需要一个步骤']

  const seen = new Set<number>()
  for (const step of steps) {
    if (step.no < 0) errors.push(`步骤序号不能为负：${step.no}`)
    if (seen.has(step.no)) errors.push(`步骤序号重复：${step.no}`)
    seen.add(step.no)
    if (!step.title.trim()) errors.push(`步骤 ${step.no} 缺少标题`)
    if (!step.instruction.trim()) errors.push(`步骤 ${step.no} 缺少指令`)
    if (!step.skill.trim()) errors.push(`步骤 ${step.no} 缺少能力`)
  }

  for (const step of steps) {
    for (const dep of step.depends_on) {
      if (dep === step.no) errors.push(`步骤 ${step.no} 不能依赖自身`)
      else if (!seen.has(dep)) errors.push(`步骤 ${step.no} 依赖了不存在的步骤：${dep}`)
    }
  }

  if (errors.length === 0 && hasCycle(steps)) errors.push('步骤依赖存在环，无法编排')
  return errors
}

/** 编辑器行：Form.List 每行一步；no 不入表单，提交时按行序赋值。depends_on 存「行下标」。 */
export interface StepRow {
  title?: string
  skill?: string
  instruction?: string
  depends_on?: number[]
  expert_code?: string
}

/** 后端步骤 → 编辑器行：按 no 排序，depends_on 从 no 重映射为行下标（no 可能非连续）。 */
export function stepsToRows(steps: WorkflowStep[]): StepRow[] {
  const sorted = [...steps].sort((a, b) => a.no - b.no)
  const posByNo = new Map(sorted.map((s, i) => [s.no, i]))
  return sorted.map((s) => ({
    title: s.title,
    skill: s.skill,
    instruction: s.instruction,
    depends_on: s.depends_on.map((d) => posByNo.get(d)).filter((p): p is number => p !== undefined),
    expert_code: s.expert_code ?? undefined,
  }))
}

/** 编辑器行 → 后端步骤：no = 行下标；去自依赖，其余非法引用交 validateSteps 兜底拦截。 */
export function rowsToSteps(rows: StepRow[]): WorkflowStep[] {
  return rows.map((row, i) => ({
    no: i,
    title: (row.title ?? '').trim(),
    skill: row.skill ?? '',
    instruction: (row.instruction ?? '').trim(),
    depends_on: (row.depends_on ?? []).filter((d) => d !== i),
    expert_code: row.expert_code?.trim() ? row.expert_code.trim() : null,
  }))
}

/** Kahn 拓扑排序：排不完（剩下的构成环）即有环。前置：depends_on 已确保引用合法、无自依赖。 */
function hasCycle(steps: WorkflowStep[]): boolean {
  const indegree = new Map<number, number>()
  const dependents = new Map<number, number[]>()
  for (const step of steps) {
    indegree.set(step.no, step.depends_on.length)
    dependents.set(step.no, [])
  }
  for (const step of steps) {
    for (const dep of step.depends_on) dependents.get(dep)?.push(step.no)
  }

  const queue = [...indegree].filter(([, deg]) => deg === 0).map(([no]) => no)
  let resolved = 0
  while (queue.length) {
    const no = queue.pop() as number
    resolved += 1
    for (const next of dependents.get(no) ?? []) {
      const deg = (indegree.get(next) ?? 0) - 1
      indegree.set(next, deg)
      if (deg === 0) queue.push(next)
    }
  }
  return resolved !== steps.length
}

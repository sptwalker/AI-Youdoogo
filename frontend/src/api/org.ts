/** 组织架构 API（对应后端 app/api/v1/org.py）。 */
import { request } from './client'

export interface OrgNode {
  id: string
  name: string
  code: string
  node_type: 'company' | 'dept_l1' | 'dept_l2'
  level: number
  parent_id: string | null
  supervisor_user_id: string | null
  employee_count: number
  children: OrgNode[]
}

export interface Employee {
  id: string
  code: string | null
  name: string
  title: string
  tier: 'exec' | 'director' | 'member'
  department_id: string | null
  report_to_id: string | null
  model_role: string
  duty: string | null
  prompt_template: string
  is_seed: boolean
  is_active: boolean
}

export const TIER_LABEL: Record<string, string> = {
  exec: '公司顾问',
  director: '总监助理',
  member: '助理',
}

export function getTree(): Promise<OrgNode[]> {
  return request({ method: 'GET', url: '/org/tree' })
}

/** 把嵌套部门树拍平为下拉选项（名称带层级缩进）。 */
export function flattenDepts(nodes: OrgNode[]): { value: string; label: string }[] {
  const out: { value: string; label: string }[] = []
  const walk = (ns: OrgNode[], prefix: string) =>
    ns.forEach((n) => {
      out.push({ value: n.id, label: prefix + n.name })
      walk(n.children, prefix + '　')
    })
  walk(nodes, '')
  return out
}

export function initTemplate(): Promise<{ departments: number; execs: number; directors: number }> {
  return request({ method: 'POST', url: '/org/init-template' })
}

export function createNode(payload: { name: string; parent_id: string; code?: string }) {
  return request({ method: 'POST', url: '/org/nodes', data: payload })
}

export function updateNode(id: string, payload: { name?: string; sort_order?: number }) {
  return request({ method: 'PATCH', url: `/org/nodes/${id}`, data: payload })
}

export function deleteNode(id: string): Promise<null> {
  return request({ method: 'DELETE', url: `/org/nodes/${id}` })
}

export interface EmployeePayload {
  name?: string
  prompt_template?: string
  title?: string
  tier?: string
  model_role?: string
  duty?: string
  report_to_id?: string
  is_active?: boolean
}

export function updateEmployee(id: string, payload: EmployeePayload) {
  return request({ method: 'PATCH', url: `/org/employees/${id}`, data: payload })
}

export function setSupervisor(id: string, supervisor_user_id: string | null) {
  return request({ method: 'PUT', url: `/org/nodes/${id}/supervisor`, data: { supervisor_user_id } })
}

export function listEmployees(deptId: string): Promise<Employee[]> {
  return request({ method: 'GET', url: `/org/nodes/${deptId}/employees` })
}

export function createEmployee(
  deptId: string,
  payload: {
    name: string
    prompt_template: string
    title?: string
    tier?: string
    model_role?: string
    duty?: string
    report_to_id?: string
  },
) {
  return request({ method: 'POST', url: `/org/nodes/${deptId}/employees`, data: payload })
}

export function deleteEmployee(id: string): Promise<null> {
  return request({ method: 'DELETE', url: `/org/employees/${id}` })
}

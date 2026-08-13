/** 工作流模板 API（对应后端 app/api/v1/workflow_templates.py，仅 admin）。 */
import { request } from './http'

export interface WorkflowStep {
  no: number
  title: string
  skill: string
  instruction: string
  depends_on: number[]
  expert_code: string | null
}

export interface WorkflowTemplate {
  id: string
  name: string
  description: string | null
  department_id: string | null
  steps: WorkflowStep[]
  enabled: boolean
  is_seed: boolean
}

export interface TemplatePayload {
  name: string
  description?: string | null
  department_id?: string | null
  steps: WorkflowStep[]
}

export function listTemplates(): Promise<WorkflowTemplate[]> {
  return request({ method: 'GET', url: '/workflow-templates' })
}

export function getTemplate(id: string): Promise<WorkflowTemplate> {
  return request({ method: 'GET', url: `/workflow-templates/${id}` })
}

export function createTemplate(payload: TemplatePayload): Promise<{ id: string }> {
  return request({ method: 'POST', url: '/workflow-templates', data: payload })
}

export function updateTemplate(
  id: string,
  payload: Partial<TemplatePayload & { enabled: boolean }>,
): Promise<{ id: string }> {
  return request({ method: 'PATCH', url: `/workflow-templates/${id}`, data: payload })
}

export function deleteTemplate(id: string): Promise<null> {
  return request({ method: 'DELETE', url: `/workflow-templates/${id}` })
}

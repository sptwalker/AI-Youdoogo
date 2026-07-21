import { ModalForm, ProFormSelect, ProFormSwitch, ProFormText, ProFormTextArea } from '@ant-design/pro-components'
import type { ReactElement, ReactNode } from 'react'
import { listRoles } from '../../api/agents'
import type { Employee } from '../../api/org'

const TIER_OPTIONS = [
  { value: 'exec', label: '公司顾问' },
  { value: 'director', label: '总监助理' },
  { value: 'member', label: '助理' },
]
const MODEL_OPTIONS = [
  { value: 'daily', label: '日常 (deepseek-chat)' },
  { value: 'reasoning', label: '推理 (deepseek-reasoner)' },
]

async function reportToOptions() {
  return (await listRoles()).map((role) => ({ value: role.id, label: role.name }))
}

export default function EmployeeForm(props: {
  trigger: ReactNode
  initial?: Partial<Employee> & { prompt_template?: string }
  isEdit?: boolean
  onFinish: (value: Record<string, unknown>) => Promise<void>
}) {
  return (
    <ModalForm
      title={props.isEdit ? '编辑智能体员工' : '新增智能体员工'}
      trigger={props.trigger as ReactElement}
      initialValues={props.initial ?? { tier: 'member', model_role: 'daily' }}
      modalProps={{ destroyOnHidden: true }}
      onFinish={async (value) => {
        await props.onFinish(value)
        return true
      }}
    >
      <ProFormText name="name" label="姓名" rules={[{ required: true }]} />
      <ProFormText name="title" label="职位（如 CCO / 数据分析专员）" />
      <ProFormSelect name="tier" label="层级" options={TIER_OPTIONS} rules={[{ required: true }]} />
      <ProFormSelect name="model_role" label="模型档位" options={MODEL_OPTIONS} />
      <ProFormSelect
        name="report_to_id"
        label="汇报给（可选）"
        tooltip="公司顾问直属真人 CEO（最高管理员），可不填；总监助理/助理可汇报给上级顾问或助理"
        request={reportToOptions}
      />
      <ProFormText name="duty" label="职责简述" />
      <ProFormTextArea
        name="prompt_template"
        label="系统提示词（角色人设与职责）"
        rules={props.isEdit ? [] : [{ required: true }]}
      />
      {props.isEdit && <ProFormSwitch name="is_active" label="启用" />}
    </ModalForm>
  )
}

/** 工作流模板管理（仅 admin，docs/25 P5-2）：ProTable 列表 + 步骤 DAG 编辑器。
 *  模板只是「钉死的步骤蓝图」；发起/执行/红线停点仍走 P4 编排入口，本页只碰模板定义。
 *  步骤编辑器为全仓首个 Form.List 用例：每行一步，depends_on 联动「其它步」，提交前跑纯校验（后端仍权威）。 */
import {
  ModalForm,
  PageContainer,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components'
import { Button, Form, Popconfirm, Space, Switch, Tag, Typography, message } from 'antd'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { listSkills, type SkillInfo } from '../api/agents'
import { flattenDepts, getTree } from '../api/org'
import {
  createTemplate,
  deleteTemplate,
  listTemplates,
  updateTemplate,
  type WorkflowTemplate,
} from '../api/workflowTemplates'
import {
  rowsToSteps,
  stepsToRows,
  validateSteps,
  type StepRow,
} from './workflowTemplateForm'

const RISK_LABEL: Record<string, string> = { low: '低风险', medium: '中风险', high: '高风险' }
const SIDE_EFFECT_LABEL: Record<string, string> = {
  none: '',
  internal_write: '· 内部写',
  external_write: '· 对外',
}

interface FormValues {
  name: string
  description?: string
  department_id?: string
  steps?: StepRow[]
}

/** 单步字段组：title/instruction/skill/depends_on/expert_code；depends_on 选项 = 其它步（Form.useWatch 联动）。 */
function StepRowFields({
  name,
  index,
  skills,
}: {
  name: number
  index: number
  skills: SkillInfo[]
}) {
  const form = Form.useFormInstance()
  const steps = (Form.useWatch('steps', form) ?? []) as StepRow[]
  const dependOptions = steps
    .map((s, i) => ({ label: `步骤${i + 1}·${s?.title?.trim() || '未命名'}`, value: i }))
    .filter((opt) => opt.value !== index)
  const skillOptions = skills.map((s) => ({
    value: s.key,
    label: `${s.label}${s.risk ? ` · ${RISK_LABEL[s.risk] ?? s.risk}` : ''}${
      s.side_effect ? ` ${SIDE_EFFECT_LABEL[s.side_effect] ?? ''}` : ''
    }`.trim(),
  }))

  return (
    <>
      <ProFormText
        name={[name, 'title']}
        label={`步骤 ${index + 1} · 标题`}
        rules={[{ required: true, max: 200 }]}
      />
      <ProFormSelect
        name={[name, 'skill']}
        label="能力"
        options={skillOptions}
        rules={[{ required: true }]}
        tooltip="仅可选已注册能力；风险/副作用徽标供参考，红线停点由运行时判定"
      />
      <ProFormTextArea
        name={[name, 'instruction']}
        label="指令"
        fieldProps={{ maxLength: 2000, autoSize: { minRows: 2, maxRows: 6 } }}
        rules={[{ required: true }]}
      />
      <ProFormSelect
        name={[name, 'depends_on']}
        label="依赖步骤"
        options={dependOptions}
        fieldProps={{ mode: 'multiple' }}
        tooltip="本步开始前须完成的其它步；不可自依赖、不可成环（保存前校验）"
      />
      <ProFormText
        name={[name, 'expert_code']}
        label="指派专家 code（可选）"
        fieldProps={{ maxLength: 64 }}
        tooltip="留空则用能力默认执行者；未知 code 运行期优雅回落"
      />
    </>
  )
}

/** 新建/编辑模板弹窗：name/description/department_id + Form.List 步骤编辑器。template 省略 = 新建。 */
function TemplateModal({
  title,
  trigger,
  template,
  skills,
  deptOptions,
  onDone,
}: {
  title: string
  trigger: ReactNode
  template?: WorkflowTemplate
  skills: SkillInfo[]
  deptOptions: { value: string; label: string }[]
  onDone: () => void
}) {
  const initialValues: FormValues = template
    ? {
        name: template.name,
        description: template.description ?? undefined,
        department_id: template.department_id ?? undefined,
        steps: stepsToRows(template.steps),
      }
    : { name: '', steps: [] }

  return (
    <ModalForm<FormValues>
      title={title}
      trigger={trigger as React.ReactElement}
      width={900}
      modalProps={{ destroyOnHidden: true }}
      initialValues={initialValues}
      onFinish={async (v) => {
        const steps = rowsToSteps(v.steps ?? [])
        const errors = validateSteps(steps)
        if (errors.length) {
          message.error(errors[0])
          return false
        }
        const payload = {
          name: v.name,
          description: v.description?.trim() || null,
          department_id: v.department_id || null,
          steps,
        }
        if (template) await updateTemplate(template.id, payload)
        else await createTemplate(payload)
        message.success('已保存')
        onDone()
        return true
      }}
    >
      <ProFormText name="name" label="模板名称" rules={[{ required: true, max: 100 }]} />
      <ProFormTextArea
        name="description"
        label="描述"
        fieldProps={{ maxLength: 2000, autoSize: { minRows: 1, maxRows: 3 } }}
      />
      <ProFormSelect
        name="department_id"
        label="归属部门（可选）"
        options={deptOptions}
        fieldProps={{ allowClear: true, showSearch: true }}
        tooltip="留空 = 全公司通用；本轮部门归属仅供归类，非-admin 自助写为后续阶段"
      />
      <Typography.Text strong>步骤（按依赖构成 DAG）</Typography.Text>
      <Form.List name="steps">
        {(fields, { add, remove }) => (
          <div style={{ marginTop: 8 }}>
            {fields.map((field, index) => (
              <div
                key={field.key}
                style={{ border: '1px solid #f0f0f0', borderRadius: 6, padding: 12, marginBottom: 12 }}
              >
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 4 }}>
                  <Button type="link" danger size="small" onClick={() => remove(field.name)}>
                    删除本步
                  </Button>
                </div>
                <StepRowFields name={field.name} index={index} skills={skills} />
              </div>
            ))}
            <Button type="dashed" block onClick={() => add({ depends_on: [] })}>
              + 添加步骤
            </Button>
          </div>
        )}
      </Form.List>
    </ModalForm>
  )
}

export default function WorkflowTemplates() {
  const actionRef = useRef<ActionType>(null)
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [deptOptions, setDeptOptions] = useState<{ value: string; label: string }[]>([])

  useEffect(() => {
    void listSkills().then(setSkills).catch(() => message.error('加载能力列表失败'))
    void getTree()
      .then((tree) => setDeptOptions(flattenDepts(tree)))
      .catch(() => message.error('加载部门列表失败'))
  }, [])

  const deptName = (id: string | null) =>
    id ? deptOptions.find((d) => d.value === id)?.label ?? id : '全公司通用'

  const columns: ProColumns<WorkflowTemplate>[] = [
    { title: '名称', dataIndex: 'name' },
    { title: '描述', dataIndex: 'description', ellipsis: true, render: (_, r) => r.description || '—' },
    { title: '归属部门', render: (_, r) => deptName(r.department_id) },
    { title: '步数', render: (_, r) => r.steps.length },
    {
      title: '种子',
      render: (_, r) => (r.is_seed ? <Tag color="blue">系统种子</Tag> : <Tag>自建</Tag>),
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      render: (_, r) => (
        <Switch
          checked={r.enabled}
          onChange={async (checked) => {
            await updateTemplate(r.id, { enabled: checked })
            message.success(checked ? '已启用' : '已停用')
            actionRef.current?.reload()
          }}
        />
      ),
    },
    {
      title: '操作',
      valueType: 'option',
      render: (_, row) => [
        <TemplateModal
          key="edit"
          title={`编辑 · ${row.name}`}
          trigger={<a>编辑</a>}
          template={row}
          skills={skills}
          deptOptions={deptOptions}
          onDone={() => actionRef.current?.reload()}
        />,
        row.is_seed ? (
          // 种子模板不可删（后端亦拒），仅可停用。
          <Typography.Text key="del" type="secondary" title="系统种子模板不可删除，可停用">
            删除
          </Typography.Text>
        ) : (
          <Popconfirm
            key="del"
            title="删除该模板？"
            description="软删除，历史发起记录不受影响。"
            okText="删除"
            okButtonProps={{ danger: true }}
            onConfirm={async () => {
              await deleteTemplate(row.id)
              message.success('已删除')
              actionRef.current?.reload()
            }}
          >
            <a style={{ color: '#cf1322' }}>删除</a>
          </Popconfirm>
        ),
      ],
    },
  ]

  return (
    <PageContainer
      title="工作流模板"
      subTitle="把重复性多步骤任务钉成可复用蓝图；发起与红线停点仍走运行时，本页只维护模板定义"
    >
      <ProTable<WorkflowTemplate>
        rowKey="id"
        actionRef={actionRef}
        search={false}
        columns={columns}
        request={async () => ({ data: await listTemplates(), success: true })}
        toolBarRender={() => [
          <Space key="new">
            <TemplateModal
              title="新建模板"
              trigger={<Button type="primary">新建模板</Button>}
              skills={skills}
              deptOptions={deptOptions}
              onDone={() => actionRef.current?.reload()}
            />
          </Space>,
        ]}
      />
    </PageContainer>
  )
}

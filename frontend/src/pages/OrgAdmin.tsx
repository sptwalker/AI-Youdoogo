/** 组织架构（仅 admin）：部门树 + 一键初始化 + 建/改/删部门 + 设主管 + 员工增删改。 */
import {
  ModalForm,
  PageContainer,
  ProFormSelect,
  ProFormSwitch,
  ProFormText,
  ProFormTextArea,
  ProTable,
  type ProColumns,
} from '@ant-design/pro-components'
import { Button, Card, Popconfirm, Select, Space, Tag, Tree, message } from 'antd'
import { type ReactNode, useEffect, useState } from 'react'
import { listRoles } from '../api/agents'
import { listUsers, type UserInfo } from '../api/auth'
import {
  createEmployee,
  createNode,
  deleteEmployee,
  deleteNode,
  getTree,
  listEmployees,
  setSupervisor,
  TIER_LABEL,
  updateEmployee,
  updateNode,
  type Employee,
  type OrgNode,
} from '../api/org'

const TIER_COLOR: Record<string, string> = { exec: 'red', director: 'blue', member: 'default' }
const TIER_OPTIONS = [
  { value: 'exec', label: '公司顾问' },
  { value: 'director', label: '总监助理' },
  { value: 'member', label: '助理' },
]
const MODEL_OPTIONS = [
  { value: 'daily', label: '日常 (deepseek-chat)' },
  { value: 'reasoning', label: '推理 (deepseek-reasoner)' },
]

interface TreeItem {
  key: string
  title: string
  node: OrgNode
  children?: TreeItem[]
}

function toTree(nodes: OrgNode[]): TreeItem[] {
  return nodes.map((n) => ({
    key: n.id,
    title: `${n.name}${n.node_type === 'company' ? ' (公司)' : ''}${
      n.employee_count ? ` · ${n.employee_count}` : ''
    }`,
    node: n,
    children: n.children.length ? toTree(n.children) : undefined,
  }))
}

/** 从组织树汇总：一级部门数 / 二级部门数 / AI 员工总数。 */
function orgStats(tree: OrgNode[]): { l1: number; l2: number; emps: number } {
  const root = tree[0]
  if (!root) return { l1: 0, l2: 0, emps: 0 }
  let emps = 0
  const walk = (n: OrgNode) => {
    emps += n.employee_count
    n.children.forEach(walk)
  }
  walk(root)
  const l2 = root.children.reduce((s, c) => s + c.children.length, 0)
  return { l1: root.children.length, l2, emps }
}

function findNode(nodes: OrgNode[], id: string): OrgNode | null {
  for (const n of nodes) {
    if (n.id === id) return n
    const f = findNode(n.children, id)
    if (f) return f
  }
  return null
}

async function reportToOptions() {
  const roles = await listRoles()
  return roles.map((r) => ({ value: r.id, label: r.name }))
}

/** 员工新增/编辑共用表单。edit 传入 initial 即为编辑。 */
function EmployeeForm(props: {
  trigger: ReactNode
  initial?: Partial<Employee> & { prompt_template?: string }
  isEdit?: boolean
  onFinish: (v: Record<string, unknown>) => Promise<void>
}) {
  return (
    <ModalForm
      title={props.isEdit ? '编辑智能体员工' : '新增智能体员工'}
      trigger={props.trigger as React.ReactElement}
      initialValues={props.initial ?? { tier: 'member', model_role: 'daily' }}
      modalProps={{ destroyOnHidden: true }}
      onFinish={async (v) => {
        await props.onFinish(v)
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

export default function OrgAdmin() {
  const [tree, setTree] = useState<OrgNode[]>([])
  const [users, setUsers] = useState<UserInfo[]>([])
  const [selected, setSelected] = useState<OrgNode | null>(null)
  const [employees, setEmployees] = useState<Employee[]>([])

  const refreshTree = async (keepId?: string) => {
    const t = await getTree()
    setTree(t)
    const id = keepId ?? selected?.id
    if (id) setSelected(findNode(t, id))
  }
  const refreshEmps = async (deptId: string) => setEmployees(await listEmployees(deptId))

  useEffect(() => {
    getTree().then(setTree)
    listUsers().then(setUsers).catch(() => {})
  }, [])

  const pickNode = async (node: OrgNode) => {
    setSelected(node)
    await refreshEmps(node.id)
  }

  const empColumns: ProColumns<Employee>[] = [
    { title: '姓名', dataIndex: 'name' },
    { title: '职位', dataIndex: 'title', render: (_, r) => r.title || '-' },
    {
      title: '层级',
      dataIndex: 'tier',
      render: (_, r) => <Tag color={TIER_COLOR[r.tier]}>{TIER_LABEL[r.tier]}</Tag>,
    },
    { title: '模型', dataIndex: 'model_role' },
    {
      title: '启用',
      dataIndex: 'is_active',
      render: (_, r) => <Tag color={r.is_active ? 'success' : 'default'}>{r.is_active ? '启用' : '停用'}</Tag>,
    },
    {
      title: '操作',
      valueType: 'option',
      render: (_, r) => [
        <EmployeeForm
          key="e"
          isEdit
          trigger={<a>编辑</a>}
          initial={r}
          onFinish={async (v) => {
            await updateEmployee(r.id, v)
            message.success('已更新')
            refreshEmps(selected!.id)
          }}
        />,
        <Popconfirm
          key="d"
          title="删除该智能体？（模板岗位可在「一键初始化」时按需补回）"
          onConfirm={async () => {
            await deleteEmployee(r.id)
            message.success('已删除')
            refreshEmps(selected!.id)
          }}
        >
          <a>删除</a>
        </Popconfirm>,
      ],
    },
  ]

  const addSubDept = async (label: string) => {
    const name = prompt(`${label}名称`)
    if (name && selected) {
      await createNode({ name, parent_id: selected.id })
      message.success(`已新建${label}`)
      refreshTree()
    }
  }

  return (
    <PageContainer title="组织架构">
      <Space align="start" style={{ width: '100%' }} size="large">
        <Card
          title="部门树"
          style={{ width: 340, flexShrink: 0 }}
          extra={
            tree.length > 0 && (
              <span style={{ fontSize: 12, color: '#888' }}>
                {(() => {
                  const s = orgStats(tree)
                  return `${s.l1} 个一级 · ${s.l2} 个二级 · ${s.emps} AI员工`
                })()}
              </span>
            )
          }
        >
          {tree.length === 0 ? (
            <span style={{ color: '#999' }}>
              暂无组织架构，请到「系统设置」一键初始化公司骨架
            </span>
          ) : (
            <Tree
              treeData={toTree(tree)}
              defaultExpandAll
              onSelect={(_, { node }) => pickNode((node as unknown as TreeItem).node)}
            />
          )}
        </Card>

        {selected && (
          <Card
            title={
              <Space>
                <span>{selected.name}</span>
                <Tag>{selected.node_type}</Tag>
                {selected.node_type !== 'company' && (
                  <a
                    onClick={async () => {
                      const name = prompt('新部门名', selected.name)
                      if (name && name !== selected.name) {
                        await updateNode(selected.id, { name })
                        message.success('已改名')
                        refreshTree()
                      }
                    }}
                  >
                    改名
                  </a>
                )}
              </Space>
            }
            style={{ flex: 1 }}
          >
            <Space direction="vertical" style={{ width: '100%' }} size="middle">
              <Space wrap>
                <span>真人主管：</span>
                <Select
                  style={{ width: 220 }}
                  allowClear
                  placeholder="选择该部门真人主管"
                  value={selected.supervisor_user_id || undefined}
                  options={users.map((u) => ({ value: u.id, label: u.real_name || u.username }))}
                  onChange={async (v) => {
                    await setSupervisor(selected.id, v ?? null)
                    message.success('主管已更新')
                    refreshTree()
                  }}
                />
                {selected.node_type === 'company' && (
                  <Button size="small" onClick={() => addSubDept('一级部门')}>+ 一级部门</Button>
                )}
                {selected.node_type === 'dept_l1' && (
                  <Button size="small" onClick={() => addSubDept('二级部门')}>+ 二级部门</Button>
                )}
                {selected.node_type !== 'company' && (
                  <Popconfirm
                    title="删除该部门？（有子部门/员工会被拒绝）"
                    onConfirm={async () => {
                      await deleteNode(selected.id)
                      message.success('已删除')
                      setSelected(null)
                      refreshTree('')
                    }}
                  >
                    <Button size="small" danger>删除部门</Button>
                  </Popconfirm>
                )}
              </Space>

              <ProTable<Employee>
                rowKey="id"
                headerTitle={`AI 顾问/助理（${selected.node_type === 'company' ? '公司顾问挂此' : '本部门总监助理/助理'}）`}
                search={false}
                options={false}
                pagination={false}
                dataSource={employees}
                columns={empColumns}
                toolBarRender={() => [
                  <EmployeeForm
                    key="add"
                    trigger={<Button type="primary">新增员工</Button>}
                    initial={{
                      tier: selected.node_type === 'company' ? 'exec' : 'member',
                      model_role: selected.node_type === 'company' ? 'reasoning' : 'daily',
                    }}
                    onFinish={async (v) => {
                      await createEmployee(selected.id, v as never)
                      message.success('已新增员工')
                      refreshEmps(selected.id)
                    }}
                  />,
                ]}
              />
            </Space>
          </Card>
        )}
      </Space>
    </PageContainer>
  )
}

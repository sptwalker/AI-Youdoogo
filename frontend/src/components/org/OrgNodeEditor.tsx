import { ProTable, type ProColumns } from '@ant-design/pro-components'
import { Button, Card, Popconfirm, Select, Space, Tag } from 'antd'
import type { UserInfo } from '../../api/auth'
import { TIER_LABEL, type Employee, type OrgNode } from '../../api/org'
import EmployeeForm from './EmployeeForm'

const TIER_COLOR: Record<string, string> = { exec: 'red', director: 'blue', member: 'default' }

export default function OrgNodeEditor(props: {
  employees: Employee[]
  node: OrgNode
  users: UserInfo[]
  onAddEmployee: (value: Record<string, unknown>) => Promise<void>
  onAddSubDepartment: (label: string) => Promise<void>
  onDeleteEmployee: (employeeId: string) => Promise<void>
  onDeleteNode: () => Promise<void>
  onRename: () => Promise<void>
  onSetSupervisor: (userId: string | null) => Promise<void>
  onUpdateEmployee: (employeeId: string, value: Record<string, unknown>) => Promise<void>
}) {
  const { employees, node, users } = props
  const columns: ProColumns<Employee>[] = [
    { title: '姓名', dataIndex: 'name' },
    { title: '职位', dataIndex: 'title', render: (_, employee) => employee.title || '-' },
    {
      title: '层级', dataIndex: 'tier',
      render: (_, employee) => <Tag color={TIER_COLOR[employee.tier]}>{TIER_LABEL[employee.tier]}</Tag>,
    },
    { title: '模型', dataIndex: 'model_role' },
    {
      title: '启用', dataIndex: 'is_active',
      render: (_, employee) => <Tag color={employee.is_active ? 'success' : 'default'}>{employee.is_active ? '启用' : '停用'}</Tag>,
    },
    {
      title: '操作', valueType: 'option',
      render: (_, employee) => [
        <EmployeeForm
          key="e" isEdit trigger={<a>编辑</a>} initial={employee}
          onFinish={(value) => props.onUpdateEmployee(employee.id, value)}
        />,
        <Popconfirm key="d" title="删除该智能体？（模板岗位可在「一键初始化」时按需补回）" onConfirm={() => props.onDeleteEmployee(employee.id)}>
          <a>删除</a>
        </Popconfirm>,
      ],
    },
  ]

  return (
    <Card
      title={
        <Space>
          <span>{node.name}</span>
          <Tag>{node.node_type}</Tag>
          {node.node_type !== 'company' && <a onClick={() => void props.onRename()}>改名</a>}
        </Space>
      }
      style={{ flex: 1 }}
    >
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <Space wrap>
          <span>真人主管：</span>
          <Select
            style={{ width: 220 }} allowClear placeholder="选择该部门真人主管"
            value={node.supervisor_user_id || undefined}
            options={users.map((user) => ({ value: user.id, label: user.real_name || user.username }))}
            onChange={(value) => void props.onSetSupervisor(value ?? null)}
          />
          {node.node_type === 'company' && <Button size="small" onClick={() => void props.onAddSubDepartment('一级部门')}>+ 一级部门</Button>}
          {node.node_type === 'dept_l1' && <Button size="small" onClick={() => void props.onAddSubDepartment('二级部门')}>+ 二级部门</Button>}
          {node.node_type !== 'company' && (
            <Popconfirm title="删除该部门？（有子部门/员工会被拒绝）" onConfirm={props.onDeleteNode}>
              <Button size="small" danger>删除部门</Button>
            </Popconfirm>
          )}
        </Space>

        <ProTable<Employee>
          rowKey="id"
          headerTitle={`AI 顾问/助理（${node.node_type === 'company' ? '公司顾问挂此' : '本部门总监助理/助理'}）`}
          search={false} options={false} pagination={false} dataSource={employees} columns={columns}
          toolBarRender={() => [
            <EmployeeForm
              key="add" trigger={<Button type="primary">新增员工</Button>}
              initial={{
                tier: node.node_type === 'company' ? 'exec' : 'member',
                model_role: node.node_type === 'company' ? 'reasoning' : 'daily',
              }}
              onFinish={props.onAddEmployee}
            />,
          ]}
        />
      </Space>
    </Card>
  )
}

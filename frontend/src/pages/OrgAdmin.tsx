/** 组织架构路由容器：加载树与员工数据，委派树和编辑器组件。 */
import { PageContainer } from '@ant-design/pro-components'
import { Button, Popconfirm, Space, message } from 'antd'
import { useEffect, useState } from 'react'
import { listUsers, type UserInfo } from '../api/auth'
import {
  createEmployee,
  createNode,
  deleteEmployee,
  deleteNode,
  getTree,
  listEmployees,
  setSupervisor,
  syncFeishu,
  updateEmployee,
  updateNode,
  type Employee,
  type OrgNode,
} from '../api/org'
import OrgNodeEditor from '../components/org/OrgNodeEditor'
import OrgTreeCard from '../components/org/OrgTreeCard'

function findNode(nodes: OrgNode[], id: string): OrgNode | null {
  for (const node of nodes) {
    if (node.id === id) return node
    const found = findNode(node.children, id)
    if (found) return found
  }
  return null
}

export default function OrgAdmin() {
  const [tree, setTree] = useState<OrgNode[]>([])
  const [users, setUsers] = useState<UserInfo[]>([])
  const [selected, setSelected] = useState<OrgNode | null>(null)
  const [employees, setEmployees] = useState<Employee[]>([])

  const refreshTree = async (keepId?: string) => {
    const nextTree = await getTree()
    setTree(nextTree)
    const id = keepId ?? selected?.id
    if (id) setSelected(findNode(nextTree, id))
  }
  const refreshEmployees = async (departmentId: string) => {
    setEmployees(await listEmployees(departmentId))
  }

  useEffect(() => {
    void getTree().then(setTree)
    void listUsers().then(setUsers).catch(() => {})
  }, [])

  const selectNode = async (node: OrgNode) => {
    setSelected(node)
    await refreshEmployees(node.id)
  }

  const addSubDepartment = async (label: string) => {
    const name = prompt(`${label}名称`)
    if (!name || !selected) return
    await createNode({ name, parent_id: selected.id })
    message.success(`已新建${label}`)
    await refreshTree()
  }

  return (
    <PageContainer
      title="组织架构"
      extra={[
        <Popconfirm
          key="sync"
          title="从飞书通讯录同步组织架构与员工身份？（需已配置飞书应用凭证）"
          onConfirm={async () => {
            const r = await syncFeishu()
            message.success(`已同步 ${r.departments} 部门，新增 ${r.users_created} 人`)
            await refreshTree()
          }}
        >
          <Button>从飞书同步</Button>
        </Popconfirm>,
      ]}
    >
      <Space align="start" style={{ width: '100%' }} size="large">
        <OrgTreeCard tree={tree} onSelect={selectNode} />
        {selected && (
          <OrgNodeEditor
            node={selected} users={users} employees={employees}
            onAddSubDepartment={addSubDepartment}
            onRename={async () => {
              const name = prompt('新部门名', selected.name)
              if (!name || name === selected.name) return
              await updateNode(selected.id, { name })
              message.success('已改名')
              await refreshTree()
            }}
            onSetSupervisor={async (userId) => {
              await setSupervisor(selected.id, userId)
              message.success('主管已更新')
              await refreshTree()
            }}
            onDeleteNode={async () => {
              await deleteNode(selected.id)
              message.success('已删除')
              setSelected(null)
              await refreshTree('')
            }}
            onAddEmployee={async (value) => {
              await createEmployee(selected.id, value as never)
              message.success('已新增员工')
              await refreshEmployees(selected.id)
            }}
            onUpdateEmployee={async (employeeId, value) => {
              await updateEmployee(employeeId, value)
              message.success('已更新')
              await refreshEmployees(selected.id)
            }}
            onDeleteEmployee={async (employeeId) => {
              await deleteEmployee(employeeId)
              message.success('已删除')
              await refreshEmployees(selected.id)
            }}
          />
        )}
      </Space>
    </PageContainer>
  )
}

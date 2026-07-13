/** 组织架构（仅 admin）：部门树 + 一键初始化骨架 + 建/删部门 + 设真人主管 + 部门员工。 */
import { PageContainer, ProTable, type ProColumns } from '@ant-design/pro-components'
import { Button, Card, Popconfirm, Select, Space, Tag, Tree, message } from 'antd'
import { useEffect, useState } from 'react'
import { listUsers, type UserInfo } from '../api/auth'
import {
  createNode,
  deleteEmployee,
  deleteNode,
  getTree,
  initTemplate,
  listEmployees,
  setSupervisor,
  TIER_LABEL,
  type Employee,
  type OrgNode,
} from '../api/org'

const TIER_COLOR: Record<string, string> = { exec: 'red', director: 'blue', member: 'default' }

interface TreeItem {
  key: string
  title: string
  node: OrgNode
  children?: TreeItem[]
}

function toTree(nodes: OrgNode[]): TreeItem[] {
  return nodes.map((n) => ({
    key: n.id,
    title: `${n.name}${n.node_type === 'company' ? ' (公司)' : ''}`,
    node: n,
    children: n.children.length ? toTree(n.children) : undefined,
  }))
}

function findNode(nodes: OrgNode[], id: string): OrgNode | null {
  for (const n of nodes) {
    if (n.id === id) return n
    const f = findNode(n.children, id)
    if (f) return f
  }
  return null
}

export default function OrgAdmin() {
  const [tree, setTree] = useState<OrgNode[]>([])
  const [users, setUsers] = useState<UserInfo[]>([])
  const [selected, setSelected] = useState<OrgNode | null>(null)
  const [employees, setEmployees] = useState<Employee[]>([])

  const reload = async () => {
    const t = await getTree()
    setTree(t)
    if (selected) setSelected(findNode(t, selected.id))
  }
  useEffect(() => {
    getTree().then(setTree)
    listUsers().then(setUsers).catch(() => {})
  }, [])

  const pickNode = async (node: OrgNode) => {
    setSelected(node)
    setEmployees(await listEmployees(node.id))
  }

  const empColumns: ProColumns<Employee>[] = [
    { title: '姓名', dataIndex: 'name' },
    { title: '职位', dataIndex: 'title', render: (_, r) => r.title || '-' },
    {
      title: '层级',
      dataIndex: 'tier',
      render: (_, r) => <Tag color={TIER_COLOR[r.tier]}>{TIER_LABEL[r.tier]}</Tag>,
    },
    { title: '模型档位', dataIndex: 'model_role' },
    {
      title: '操作',
      valueType: 'option',
      render: (_, r) =>
        r.is_seed
          ? [<Tag key="s" color="gold">骨架</Tag>]
          : [
              <Popconfirm
                key="d"
                title="删除该员工？"
                onConfirm={async () => {
                  await deleteEmployee(r.id)
                  message.success('已删除')
                  setEmployees(await listEmployees(selected!.id))
                }}
              >
                <a>删除</a>
              </Popconfirm>,
            ],
    },
  ]

  return (
    <PageContainer title="组织架构">
      <Space align="start" style={{ width: '100%' }} size="large">
        <Card
          title="部门树"
          style={{ width: 340, flexShrink: 0 }}
          extra={
            <Popconfirm
              title="按模板初始化公司骨架（幂等）？"
              onConfirm={async () => {
                const r = await initTemplate()
                message.success(`已初始化：${r.departments}部门/${r.execs}高管/${r.directors}总监`)
                reload()
              }}
            >
              <Button type="primary" size="small">一键初始化骨架</Button>
            </Popconfirm>
          }
        >
          {tree.length === 0 ? (
            <span style={{ color: '#999' }}>暂无组织架构，点右上「一键初始化骨架」</span>
          ) : (
            <Tree
              treeData={toTree(tree)}
              defaultExpandAll
              onSelect={(_, { node }) => pickNode((node as unknown as TreeItem).node)}
            />
          )}
        </Card>

        {selected && (
          <Card title={`${selected.name} · ${selected.node_type}`} style={{ flex: 1 }}>
            <Space direction="vertical" style={{ width: '100%' }} size="middle">
              <Space>
                <span>真人主管：</span>
                <Select
                  style={{ width: 220 }}
                  allowClear
                  placeholder="选择该部门真人主管"
                  value={selected.supervisor_user_id || undefined}
                  options={users.map((u) => ({
                    value: u.id,
                    label: `${u.real_name || u.username}`,
                  }))}
                  onChange={async (v) => {
                    await setSupervisor(selected.id, v ?? null)
                    message.success('主管已更新')
                    reload()
                  }}
                />
                {selected.node_type !== 'company' && selected.level < 2 && (
                  <Button
                    size="small"
                    onClick={async () => {
                      const name = prompt('二级部门名称')
                      if (name) {
                        await createNode({ name, parent_id: selected.id })
                        message.success('已新建二级部门')
                        reload()
                      }
                    }}
                  >
                    + 二级部门
                  </Button>
                )}
                {selected.node_type === 'company' && (
                  <Button
                    size="small"
                    onClick={async () => {
                      const name = prompt('一级部门名称')
                      if (name) {
                        await createNode({ name, parent_id: selected.id })
                        message.success('已新建一级部门')
                        reload()
                      }
                    }}
                  >
                    + 一级部门
                  </Button>
                )}
                {selected.node_type !== 'company' && (
                  <Popconfirm
                    title="删除该部门？（有子部门/员工会被拒绝）"
                    onConfirm={async () => {
                      await deleteNode(selected.id)
                      message.success('已删除')
                      setSelected(null)
                      reload()
                    }}
                  >
                    <Button size="small" danger>删除部门</Button>
                  </Popconfirm>
                )}
              </Space>

              <ProTable<Employee>
                rowKey="id"
                headerTitle="智能体员工"
                search={false}
                options={false}
                pagination={false}
                dataSource={employees}
                columns={empColumns}
              />
            </Space>
          </Card>
        )}
      </Space>
    </PageContainer>
  )
}

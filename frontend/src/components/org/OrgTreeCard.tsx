import { Card, Tree } from 'antd'
import type { OrgNode } from '../../api/org'

interface TreeItem {
  key: string
  title: string
  node: OrgNode
  children?: TreeItem[]
}

function toTree(nodes: OrgNode[]): TreeItem[] {
  return nodes.map((node) => ({
    key: node.id,
    title: `${node.name}${node.node_type === 'company' ? ' (公司)' : ''}${node.employee_count ? ` · ${node.employee_count}` : ''}`,
    node,
    children: node.children.length ? toTree(node.children) : undefined,
  }))
}

function orgStats(tree: OrgNode[]): { l1: number; l2: number; employees: number } {
  const root = tree[0]
  if (!root) return { l1: 0, l2: 0, employees: 0 }
  let employees = 0
  const walk = (node: OrgNode) => {
    employees += node.employee_count
    node.children.forEach(walk)
  }
  walk(root)
  return {
    l1: root.children.length,
    l2: root.children.reduce((sum, child) => sum + child.children.length, 0),
    employees,
  }
}

export default function OrgTreeCard(props: {
  tree: OrgNode[]
  onSelect: (node: OrgNode) => Promise<void>
}) {
  const stats = orgStats(props.tree)
  return (
    <Card
      title="部门树"
      style={{ width: 340, flexShrink: 0 }}
      extra={props.tree.length > 0 ? (
        <span style={{ fontSize: 12, color: '#888' }}>
          {stats.l1} 个一级 · {stats.l2} 个二级 · {stats.employees} AI员工
        </span>
      ) : undefined}
    >
      {props.tree.length === 0 ? (
        <span style={{ color: '#999' }}>暂无组织架构，请到「系统设置」一键初始化公司骨架</span>
      ) : (
        <Tree<TreeItem>
          treeData={toTree(props.tree)}
          defaultExpandAll
          onSelect={(_, { node }) => void props.onSelect(node.node)}
        />
      )}
    </Card>
  )
}

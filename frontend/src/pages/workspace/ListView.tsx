/** 列表视图：任务卡只读列表，展示泳道 + 需关注预警（操作仍在「任务卡」页）。 */
import { ProTable, type ProColumns } from '@ant-design/pro-components'
import { Tag } from 'antd'
import { listTasks, STATUS_LABEL, type TaskCard } from '../../api/tasks'
import { TASK_TYPE_LABEL } from '../../features/tasks/model'
import { LANE_COLOR } from '../../features/workspace/board'

const columns: ProColumns<TaskCard>[] = [
  { title: '标题', dataIndex: 'title', ellipsis: true },
  { title: '类型', dataIndex: 'task_type', render: (_, r) => TASK_TYPE_LABEL[r.task_type] ?? r.task_type },
  { title: '泳道', dataIndex: 'lane', render: (_, r) => <Tag color={LANE_COLOR[r.lane]}>{r.lane}</Tag> },
  { title: '状态', dataIndex: 'status', render: (_, r) => STATUS_LABEL[r.status] ?? r.status },
  { title: '优先级', dataIndex: 'priority' },
  { title: '需关注', dataIndex: 'blocked', render: (_, r) => (r.blocked ? <Tag color="volcano">需关注</Tag> : '-') },
  { title: '创建时间', dataIndex: 'create_time', valueType: 'dateTime' },
]

export default function ListView() {
  return (
    <ProTable<TaskCard>
      rowKey="id"
      search={false}
      columns={columns}
      pagination={{ pageSize: 20 }}
      request={async () => {
        try {
          return { data: await listTasks(), success: true }
        } catch {
          return { data: [], success: false }
        }
      }}
    />
  )
}

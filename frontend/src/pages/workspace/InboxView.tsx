/** 收件箱页：统一待办按优先级分排序，真人勾选后批量置读/处理态（红线：只改读态、不外发）。 */
import { ProTable, type ActionType, type ProColumns } from '@ant-design/pro-components'
import { Button, Space, Tag, Tooltip, Typography, message } from 'antd'
import { useRef, useState } from 'react'
import { getDesktop, markInbox, type PendingItem } from '../../api/desktop'
import { usePendingActions } from '../../hooks/usePendingActions'

const KIND_LABEL: Record<string, string> = {
  task: '任务',
  proposal: '提案',
  resolution: '决议',
  collab: '协作',
}
const PRIORITY_COLOR: Record<string, string> = { high: 'red', urgent: 'red', normal: 'blue', low: 'default' }

const columns: ProColumns<PendingItem>[] = [
  {
    title: '分',
    dataIndex: 'score',
    width: 64,
    render: (_, r) => <Tag color={r.score >= 0.7 ? 'red' : r.score >= 0.4 ? 'orange' : 'default'}>{r.score.toFixed(2)}</Tag>,
  },
  { title: '类型', dataIndex: 'kind', width: 72, render: (_, r) => KIND_LABEL[r.kind] ?? r.kind },
  {
    title: '标题',
    dataIndex: 'title',
    render: (_, r) => (
      <Space direction="vertical" size={0}>
        <Typography.Text delete={r.is_processed} type={r.is_read ? 'secondary' : undefined}>
          {r.title}
        </Typography.Text>
        {r.ai_summary && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            💡 {r.ai_summary}
          </Typography.Text>
        )}
      </Space>
    ),
  },
  { title: '优先级', dataIndex: 'priority', width: 80, render: (_, r) => <Tag color={PRIORITY_COLOR[r.priority] ?? 'default'}>{r.priority}</Tag> },
  {
    title: '状态',
    width: 120,
    render: (_, r) => (
      <Space size={4}>
        {r.is_read ? <Tag color="default">已读</Tag> : <Tag color="blue">未读</Tag>}
        {r.is_processed && <Tag color="success">已处理</Tag>}
      </Space>
    ),
  },
  { title: '到达时间', dataIndex: 'create_time', valueType: 'dateTime', width: 160 },
]

export default function InboxView() {
  const actionRef = useRef<ActionType>(null)
  const pending = usePendingActions()
  const [selected, setSelected] = useState<PendingItem[]>([])

  const applyMark = (action: { is_read?: boolean; is_processed?: boolean }, label: string) => {
    if (!selected.length) return
    void pending
      .run('mark', async () => {
        const refs = selected.map((i) => ({ kind: i.kind, id: i.id }))
        const { marked } = await markInbox(refs, action)
        message.success(`已${label} ${marked} 项`)
        setSelected([])
        actionRef.current?.reload()
      })
      .catch(() => {})
  }

  return (
    <ProTable<PendingItem>
      rowKey={(r) => `${r.kind}:${r.id}`}
      actionRef={actionRef}
      search={false}
      columns={columns}
      pagination={false}
      rowSelection={{
        selectedRowKeys: selected.map((i) => `${i.kind}:${i.id}`),
        onChange: (_keys, rows) => setSelected(rows),
      }}
      tableAlertOptionRender={() => (
        <Space>
          {/* 红线：批量处理=真人确认触发，仅置本人读/处理态，不推进来源、不外发。 */}
          <Tooltip title="仅标记本人收件箱读态，不影响来源与他人">
            <Button size="small" loading={pending.isPending('mark')} onClick={() => applyMark({ is_read: true }, '标记已读')}>
              标记已读
            </Button>
          </Tooltip>
          <Button size="small" type="primary" loading={pending.isPending('mark')} onClick={() => applyMark({ is_read: true, is_processed: true }, '标记已处理')}>
            标记已处理
          </Button>
        </Space>
      )}
      request={async () => {
        try {
          const desk = await getDesktop()
          return { data: desk.pending, success: true }
        } catch {
          return { data: [], success: false }
        }
      }}
    />
  )
}

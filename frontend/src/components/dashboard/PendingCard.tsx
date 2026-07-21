import { Badge, Card, List, Space, Tag, Typography } from 'antd'
import type { ReactNode } from 'react'
import type { Desktop, PendingItem } from '../../api/desktop'

const KIND: Record<PendingItem['kind'], { label: string; color: string }> = {
  task: { label: '待验收', color: 'blue' },
  proposal: { label: '待评审', color: 'gold' },
  resolution: { label: '待确认', color: 'purple' },
  collab: { label: '待复核', color: 'volcano' },
}

export default function PendingCard(props: {
  data: Desktop | null
  actions: (pending: PendingItem) => ReactNode[]
}) {
  const { data, actions } = props
  return (
    <Card
      size="small"
      title={<Badge count={data?.pending_count ?? 0} showZero offset={[10, 0]}>待我处理</Badge>}
      style={{ flex: 'none' }}
      styles={{
        body: {
          maxHeight: '50vh',
          overflowY: 'auto',
          padding: data && data.pending.length === 0 ? '8px 16px' : undefined,
        },
      }}
    >
      {data && data.pending.length === 0 && <Typography.Text type="secondary">暂无待处理</Typography.Text>}
      {(!data || data.pending.length > 0) && (
        <List
          dataSource={data?.pending ?? []}
          renderItem={(pending) => (
            <List.Item actions={actions(pending)}>
              <List.Item.Meta
                title={
                  <Space>
                    <Tag color={KIND[pending.kind].color}>{KIND[pending.kind].label}</Tag>
                    {pending.title}
                  </Space>
                }
                description={
                  <Space size="small">
                    {pending.meta && <span>{pending.meta}</span>}
                    {pending.priority === 'high' && <Tag color="red">高</Tag>}
                  </Space>
                }
              />
            </List.Item>
          )}
        />
      )}
    </Card>
  )
}

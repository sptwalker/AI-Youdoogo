import { Badge, Button, Card, Empty, List, Space, Tag, Typography } from 'antd'
import type { Deliverable, Desktop } from '../../api/desktop'
import { STATUS_LABEL } from '../../api/tasks'

export default function DashboardSidebar(props: {
  data: Desktop | null
  deliverables: Deliverable[]
  isSupervising: boolean
  onDownload: (id: string, fileName: string) => Promise<void>
  onNavigate: (path: string) => void
  onRefreshDeliverables: () => Promise<void>
}) {
  const { data, deliverables, isSupervising, onDownload, onNavigate, onRefreshDeliverables } = props
  return (
    <div style={{ height: 'calc(100vh - 130px)', minHeight: 480, overflowY: 'auto', paddingRight: 4 }}>
      {!isSupervising && (
        <Card title="发起需求">
          <Space wrap>
            <Button type="primary" onClick={() => onNavigate('/tasks')}>发起任务</Button>
            <Button onClick={() => onNavigate('/proposals')}>发起提案</Button>
            <Button onClick={() => onNavigate('/discussion')}>找 AI 顾问商议</Button>
          </Space>
          <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
            发起的需求由 AI 顾问或人机混合流程处理，产出仍须你确认后生效。
          </Typography.Paragraph>
        </Card>
      )}
      <Card title="我的任务" style={{ marginTop: isSupervising ? 0 : 16 }}>
        {data && data.my_tasks.length === 0 && <Empty description="暂无进行中的任务" />}
        <List
          dataSource={data?.my_tasks ?? []}
          renderItem={(task) => (
            <List.Item actions={[<a key="v" onClick={() => onNavigate('/tasks')}>查看</a>]}>
              <List.Item.Meta
                title={task.title}
                description={<Space><Tag>{STATUS_LABEL[task.status] ?? task.status}</Tag>{task.task_type}</Space>}
              />
            </List.Item>
          )}
        />
      </Card>
      <Card
        title={<Badge count={deliverables.length} showZero offset={[10, 0]}>文件交付区</Badge>}
        style={{ marginTop: 16 }}
        extra={<a onClick={() => void onRefreshDeliverables()}>刷新</a>}
      >
        {deliverables.length === 0 && <Empty description="AI 交付的文档/表格会出现在这里" />}
        <List
          dataSource={deliverables}
          renderItem={(deliverable) => (
            <List.Item
              actions={[
                <a key="dl" onClick={() => void onDownload(deliverable.id, deliverable.file_name)}>
                  下载
                </a>,
              ]}
            >
              <List.Item.Meta
                title={<Space><Tag color="cyan">{deliverable.file_format.toUpperCase()}</Tag>{deliverable.file_name}</Space>}
                description={
                  <Typography.Text type="secondary">
                    {deliverable.agent_name || 'AI'} 交付 · {new Date(deliverable.create_time).toLocaleString()}
                  </Typography.Text>
                }
              />
            </List.Item>
          )}
        />
      </Card>
    </div>
  )
}

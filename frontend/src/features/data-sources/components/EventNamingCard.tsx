import { Button, Card, Empty, Input, Space, Spin, Tag, Typography } from 'antd'
import { eventEditKey } from '../model'
import { useEventNaming } from '../hooks/useEventNaming'

export function EventNamingCard() {
  const naming = useEventNaming()

  return (
    <Card
      title="运营事件命名"
      style={{ marginTop: 16 }}
      extra={
        <Space>
          <input
            type="date"
            value={naming.statDate}
            onChange={(event) => naming.setStatDate(event.target.value)}
            style={{ padding: '2px 6px' }}
          />
          <Button size="small" onClick={() => { void naming.load() }} loading={naming.loading}>
            查该日事件
          </Button>
          <Button
            size="small"
            type="primary"
            onClick={() => { void naming.save() }}
            loading={naming.saving}
          >
            保存命名
          </Button>
        </Space>
      }
    >
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        列出各产品当日全部事件码（按次数降序），填中文名用于报表/界面显示。别名永久保存，与日期无关；
        某天没发生的事件换日期即可补命名。
      </Typography.Paragraph>
      {naming.loading && <Spin />}
      {!naming.loading && naming.groups.length === 0 && (
        <Empty description="无数据，检查 TD 配置或换个日期" />
      )}
      {!naming.loading && naming.groups.map((group) => (
        <Card
          key={group.view}
          type="inner"
          size="small"
          title={
            <Space>
              <Tag color="blue">{group.product}</Tag>
              <Typography.Text type="secondary">{group.view}</Typography.Text>
            </Space>
          }
          style={{ marginBottom: 12 }}
        >
          {group.error && <Typography.Text type="danger">{group.error}</Typography.Text>}
          {!group.error && group.events.length === 0 && (
            <Empty description="该日无事件" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
          {group.events.map((event) => {
            const key = eventEditKey(group.view, event.event_code)
            return (
              <Space key={key} style={{ width: '100%', marginBottom: 6 }} align="center">
                <Typography.Text code style={{ width: 220, display: 'inline-block' }}>
                  {event.event_code}
                </Typography.Text>
                <Typography.Text
                  type="secondary"
                  style={{ width: 90, display: 'inline-block' }}
                >
                  {event.count} 次
                </Typography.Text>
                <Input
                  placeholder="中文名（留空清除）"
                  style={{ width: 220 }}
                  value={naming.edits[key] ?? ''}
                  onChange={(inputEvent) => naming.updateEdit(key, inputEvent.target.value)}
                />
              </Space>
            )
          })}
        </Card>
      ))}
    </Card>
  )
}

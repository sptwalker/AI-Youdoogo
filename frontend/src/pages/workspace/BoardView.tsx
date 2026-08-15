/** 看板视图：任务卡按只读派生泳道分列展示，blocked 标「需关注」。 */
import { Badge, Card, Empty, Spin, Tag, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import { listTasks, type TaskCard } from '../../api/tasks'
import { LANE_COLOR, groupByLane, laneColumns } from '../../features/workspace/board'

const PRIORITY_COLOR: Record<string, string> = { high: 'red', normal: 'blue', low: 'default' }

export default function BoardView() {
  const [tasks, setTasks] = useState<TaskCard[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    void listTasks()
      .then(setTasks)
      .catch(() => message.error('加载任务失败'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Spin style={{ display: 'block', margin: '48px auto' }} />
  if (!tasks.length) return <Empty description="暂无任务" />

  const groups = groupByLane(tasks)
  const columns = laneColumns(tasks)

  return (
    <div style={{ display: 'flex', gap: 12, overflowX: 'auto', paddingBottom: 8, alignItems: 'flex-start' }}>
      {columns.map((lane) => {
        const items = groups[lane] ?? []
        return (
          <Card
            key={lane}
            size="small"
            style={{ minWidth: 260, maxWidth: 300, flex: '0 0 auto', background: 'rgba(0,0,0,0.02)' }}
            title={
              <span>
                <Tag color={LANE_COLOR[lane]}>{lane}</Tag>
                <Badge count={items.length} showZero color="#999" />
              </span>
            }
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {items.map((t) => (
                <Card key={t.id} size="small" styles={{ body: { padding: 10 } }}>
                  <Typography.Text strong ellipsis={{ tooltip: t.title }} style={{ display: 'block' }}>
                    {t.title}
                  </Typography.Text>
                  <div style={{ marginTop: 6 }}>
                    <Tag color={PRIORITY_COLOR[t.priority] ?? 'default'}>{t.priority}</Tag>
                    {t.blocked && <Tag color="volcano">需关注</Tag>}
                  </div>
                </Card>
              ))}
              {!items.length && <Typography.Text type="secondary">—</Typography.Text>}
            </div>
          </Card>
        )
      })}
    </div>
  )
}

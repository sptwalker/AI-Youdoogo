/** 时间线视图（B4.1）：本人日程按开始时间竖向排列（AntD Timeline）。
 *
 *  隔离：走 /schedules，仅本人日程。建议态可就地「确认」（真人确认才生效，红线）。 */
import { Button, Empty, Space, Tag, Timeline, Typography, message } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { confirmSchedule, listSchedules, SCHEDULE_STATUS, type Schedule } from '../../api/schedule'

const STATUS_COLOR: Record<string, string> = {
  suggested: 'gray',
  confirmed: 'green',
  done: 'blue',
  cancelled: 'red',
}

export default function TimelineView() {
  const [rows, setRows] = useState<Schedule[]>([])
  const [confirming, setConfirming] = useState<string | null>(null)

  const reload = () => {
    void listSchedules().then(setRows).catch(() => undefined)
  }
  useEffect(reload, [])

  const onConfirm = async (id: string) => {
    setConfirming(id)
    try {
      await confirmSchedule(id)
      message.success('已确认生效')
      reload()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '确认失败')
    } finally {
      setConfirming(null)
    }
  }

  const items = useMemo(
    () =>
      [...rows]
        .sort((a, b) => a.start_at.localeCompare(b.start_at))
        .map((row) => ({
          color: STATUS_COLOR[row.status] ?? 'gray',
          children: (
            <Space direction="vertical" size={2}>
              <Space size={6} wrap>
                <Typography.Text strong>{row.title}</Typography.Text>
                <Tag>{SCHEDULE_STATUS[row.status] ?? row.status}</Tag>
              </Space>
              <Typography.Text type="secondary">
                {new Date(row.start_at).toLocaleString()} ~ {new Date(row.end_at).toLocaleString()}
              </Typography.Text>
              {row.status === 'suggested' && (
                <Button
                  size="small"
                  type="link"
                  loading={confirming === row.id}
                  onClick={() => void onConfirm(row.id)}
                >
                  确认生效
                </Button>
              )}
            </Space>
          ),
        })),
    [rows, confirming],
  )

  if (rows.length === 0) return <Empty description="暂无日程" />
  return <Timeline items={items} />
}

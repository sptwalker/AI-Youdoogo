/** 时间线视图（B4.1）：本人日程按开始时间竖向排列（AntD Timeline）。
 *
 *  隔离：走 /schedules，仅本人日程。建议态可就地「确认」（真人确认才生效，红线）。
 *  失败交全局请求拦截 toast，本视图不重复弹（避免双 toast）。 */
import { Button, Empty, Popconfirm, Space, Spin, Tag, Timeline, Typography, message } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { confirmSchedule, listSchedules, SCHEDULE_STATUS, type Schedule } from '../../api/schedule'
import FocusTimer from './FocusTimer'
import ScheduleCreateModal from './ScheduleCreateModal'

const STATUS_COLOR: Record<string, string> = {
  suggested: 'gray',
  confirmed: 'green',
  done: 'blue',
  cancelled: 'red',
}

export default function TimelineView() {
  const [rows, setRows] = useState<Schedule[]>([])
  const [loading, setLoading] = useState(true)
  const [confirming, setConfirming] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)

  const reload = () => {
    setLoading(true)
    void listSchedules()
      .then(setRows)
      .catch(() => undefined)
      .finally(() => setLoading(false))
  }
  useEffect(reload, [])

  const onConfirm = async (id: string) => {
    setConfirming(id)
    try {
      await confirmSchedule(id)
      message.success('已确认生效')
      reload()
    } catch {
      /* 失败提示已由全局请求拦截统一弹出 */
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
                <Popconfirm
                  title="确认使该建议日程生效？"
                  okText="确认生效"
                  cancelText="取消"
                  onConfirm={() => void onConfirm(row.id)}
                >
                  <Button size="small" type="link" loading={confirming === row.id}>
                    确认生效
                  </Button>
                </Popconfirm>
              )}
            </Space>
          ),
        })),
    [rows, confirming],
  )

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Space size={8} wrap style={{ justifyContent: 'space-between', width: '100%' }}>
        <FocusTimer />
        <Button type="primary" size="small" onClick={() => setCreateOpen(true)}>
          新建日程
        </Button>
      </Space>
      {loading ? (
        <Spin />
      ) : rows.length === 0 ? (
        <Empty description="暂无日程" />
      ) : (
        <Timeline items={items} />
      )}
      <ScheduleCreateModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={reload}
      />
    </Space>
  )
}

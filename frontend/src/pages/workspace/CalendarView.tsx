/** 日历视图（B4.2）：AntD Calendar，当日有日程则打点；点击某日列出当日日程并可确认建议。
 *
 *  隔离：走 /schedules，仅本人日程。红线：建议态 confirm 才生效。 */
import { Badge, Button, Calendar, Card, Empty, List, Space, Tag, message } from 'antd'
import type { Dayjs } from 'dayjs'
import { useEffect, useMemo, useState } from 'react'
import { confirmSchedule, listSchedules, SCHEDULE_STATUS, type Schedule } from '../../api/schedule'

/** 取本地日历日键 YYYY-MM-DD，用于按日分组（避免 UTC 串直接切片错位）。 */
function dayKey(iso: string): string {
  const d = new Date(iso)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export default function CalendarView() {
  const [rows, setRows] = useState<Schedule[]>([])
  const [picked, setPicked] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)

  const reload = () => {
    void listSchedules().then(setRows).catch(() => undefined)
  }
  useEffect(reload, [])

  const byDay = useMemo(() => {
    const map = new Map<string, Schedule[]>()
    for (const row of rows) {
      const key = dayKey(row.start_at)
      const list = map.get(key) ?? []
      list.push(row)
      map.set(key, list)
    }
    return map
  }, [rows])

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

  const dayList = picked ? byDay.get(picked) ?? [] : []
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Calendar
        fullscreen={false}
        onSelect={(value: Dayjs) => setPicked(value.format('YYYY-MM-DD'))}
        cellRender={(value: Dayjs) => {
          const items = byDay.get(value.format('YYYY-MM-DD')) ?? []
          return items.length > 0 ? <Badge count={items.length} size="small" /> : null
        }}
      />
      {picked && (
        <Card size="small" title={`${picked} 的日程`}>
          {dayList.length === 0 ? (
            <Empty description="当日无日程" />
          ) : (
            <List
              size="small"
              dataSource={dayList}
              renderItem={(row) => (
                <List.Item
                  actions={
                    row.status === 'suggested'
                      ? [
                          <Button
                            key="confirm"
                            size="small"
                            type="link"
                            loading={confirming === row.id}
                            onClick={() => void onConfirm(row.id)}
                          >
                            确认生效
                          </Button>,
                        ]
                      : []
                  }
                >
                  <Space size={6} wrap>
                    <span>{row.title}</span>
                    <Tag>{SCHEDULE_STATUS[row.status] ?? row.status}</Tag>
                  </Space>
                </List.Item>
              )}
            />
          )}
        </Card>
      )}
    </Space>
  )
}

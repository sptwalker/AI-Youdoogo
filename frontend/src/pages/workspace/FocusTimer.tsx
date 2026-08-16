/** 番茄钟控件（B2.3 前端接线）：开始/完成/放弃一段专注，展示进行中会话。
 *
 *  个人时间治理，不涉红线停点；失败交全局拦截 toast。
 *  ponytail: 无实时倒计时，只展示始于/计划分钟；要倒计时再加 setInterval。
 *  ponytail: 拦截「发给本人的通知」需调用侧传 recipient_user_id，属上线接线项（见 docs/27-B backlog）。 */
import { Button, Space, Tag, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import { abortFocus, completeFocus, getActiveFocus, startFocus, type FocusSession } from '../../api/schedule'

const DEFAULT_MINUTES = 25

export default function FocusTimer() {
  const [active, setActive] = useState<FocusSession | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    void getActiveFocus().then(setActive).catch(() => undefined)
  }, [])

  const run = async (fn: () => Promise<FocusSession | null>, tip: string) => {
    setBusy(true)
    try {
      const next = await fn()
      setActive(next?.status === 'active' ? next : null)
      message.success(tip)
    } catch {
      /* 失败提示已由全局请求拦截统一弹出 */
    } finally {
      setBusy(false)
    }
  }

  if (active) {
    return (
      <Space size={8} wrap>
        <Tag color="processing">专注中</Tag>
        <Typography.Text type="secondary">
          始于 {new Date(active.start_at).toLocaleTimeString()} · 计划 {active.planned_minutes} 分钟
        </Typography.Text>
        <Button size="small" loading={busy} onClick={() => void run(() => completeFocus(active.id), '专注已完成')}>
          完成
        </Button>
        <Button size="small" danger loading={busy} onClick={() => void run(() => abortFocus(active.id), '已放弃专注')}>
          放弃
        </Button>
      </Space>
    )
  }
  return (
    <Button
      size="small"
      loading={busy}
      onClick={() => void run(() => startFocus(DEFAULT_MINUTES), '开始专注')}
    >
      开始专注（{DEFAULT_MINUTES} 分钟）
    </Button>
  )
}

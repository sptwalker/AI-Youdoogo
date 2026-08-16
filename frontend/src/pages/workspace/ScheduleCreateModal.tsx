/** 新建日程弹窗（B4）：手动建一条本人日程（即 confirmed）。Timeline/Calendar 复用。
 *
 *  个人时间治理，不涉红线；失败交全局拦截 toast（本组件不重复弹）。 */
import { DatePicker, Form, Input, Modal, message } from 'antd'
import type { Dayjs } from 'dayjs'
import { useState } from 'react'
import { createSchedule } from '../../api/schedule'

interface Props {
  open: boolean
  onClose: () => void
  onCreated: () => void
}

interface FormValues {
  title: string
  range: [Dayjs, Dayjs]
}

export default function ScheduleCreateModal({ open, onClose, onCreated }: Props) {
  const [form] = Form.useForm<FormValues>()
  const [saving, setSaving] = useState(false)

  const onOk = async () => {
    let values: FormValues
    try {
      values = await form.validateFields()
    } catch {
      return // 校验未过：antd 已在字段下标红，无需额外提示
    }
    setSaving(true)
    try {
      await createSchedule({
        title: values.title,
        start_at: values.range[0].toISOString(),
        end_at: values.range[1].toISOString(),
      })
      message.success('日程已创建')
      form.resetFields()
      onCreated()
      onClose()
    } catch {
      /* 失败提示已由全局请求拦截统一弹出 */
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="新建日程"
      open={open}
      onOk={() => void onOk()}
      onCancel={onClose}
      confirmLoading={saving}
      destroyOnClose
    >
      <Form form={form} layout="vertical">
        <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
          <Input maxLength={200} placeholder="如：周会 / 客户拜访" />
        </Form.Item>
        <Form.Item
          name="range"
          label="起止时间"
          rules={[{ required: true, message: '请选择起止时间' }]}
        >
          <DatePicker.RangePicker showTime style={{ width: '100%' }} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

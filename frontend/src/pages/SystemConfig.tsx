/** 系统配置（F5b 读 + 编辑）：非密配置，改后即时生效；密钥仍走 .env（此表不含密钥）。 */
import {
  ModalForm,
  PageContainer,
  ProFormTextArea,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components'
import { Tag, Typography, message } from 'antd'
import { useRef } from 'react'
import { listConfigs, updateConfig, type SysConfig } from '../api/admin'

/** 按 value_type 把编辑框文本还原为对应 JSON 值。 */
function coerce(valueType: string, raw: string): unknown {
  if (valueType === 'int') return Number(raw)
  if (valueType === 'bool') return raw.trim().toLowerCase() === 'true'
  return raw
}

const asText = (v: unknown): string => (typeof v === 'string' ? v : JSON.stringify(v))

export default function SystemConfig() {
  const actionRef = useRef<ActionType>(null)
  const columns: ProColumns<SysConfig>[] = [
    { title: '配置项', dataIndex: 'key', copyable: true, width: 220 },
    { title: '分类', dataIndex: 'category', width: 110, render: (_, r) => <Tag>{r.category}</Tag> },
    { title: '类型', dataIndex: 'value_type', width: 90 },
    {
      title: '当前值', dataIndex: 'value', ellipsis: true,
      render: (_, r) => (
        <Typography.Text style={{ whiteSpace: 'pre-wrap' }}>{asText(r.value)}</Typography.Text>
      ),
    },
    {
      title: '操作', valueType: 'option', width: 90,
      render: (_, r) =>
        r.is_editable
          ? [
              <ModalForm<{ value: string }>
                key="e"
                title={`编辑 ${r.key}`}
                trigger={<a>编辑</a>}
                initialValues={{ value: asText(r.value) }}
                modalProps={{ destroyOnHidden: true }}
                onFinish={async (v) => {
                  await updateConfig(r.key, coerce(r.value_type, v.value))
                  message.success('已保存，即时生效')
                  actionRef.current?.reload()
                  return true
                }}
              >
                <ProFormTextArea name="value" label="值" rules={[{ required: true }]} />
              </ModalForm>,
            ]
          : [<Typography.Text key="l" type="secondary">只读</Typography.Text>],
    },
  ]
  return (
    <PageContainer title="系统配置" subTitle="非密配置改后即时生效；AI 密钥/飞书 secret 仍走 .env 不在此改">
      <ProTable<SysConfig>
        rowKey="key"
        actionRef={actionRef}
        columns={columns}
        search={false}
        options={{ reload: true, density: false, setting: false }}
        request={async () => ({ data: await listConfigs(), success: true })}
        pagination={false}
      />
    </PageContainer>
  )
}

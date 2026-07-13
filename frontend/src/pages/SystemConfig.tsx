/** 系统配置（F5b 读 + 编辑）：非密配置，改后即时生效；密钥仍走 .env（此表不含密钥）。 */
import {
  ModalForm,
  PageContainer,
  ProFormTextArea,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components'
import { Button, Card, Space, Tag, Typography, message } from 'antd'
import { useRef, useState } from 'react'
import { listConfigs, testConnectivity, updateConfig, type ConnResult, type SysConfig } from '../api/admin'

/** 按 value_type 把编辑框文本还原为对应 JSON 值。 */
function coerce(valueType: string, raw: string): unknown {
  if (valueType === 'int') return Number(raw)
  if (valueType === 'bool') return raw.trim().toLowerCase() === 'true'
  return raw
}

const asText = (v: unknown): string => (typeof v === 'string' ? v : JSON.stringify(v))

export default function SystemConfig() {
  const actionRef = useRef<ActionType>(null)
  const [conn, setConn] = useState<ConnResult[] | null>(null)
  const [testing, setTesting] = useState(false)
  const runTest = async () => {
    setTesting(true)
    try {
      setConn(await testConnectivity())
    } finally {
      setTesting(false)
    }
  }
  const CONN_COLOR: Record<ConnResult['status'], string> = {
    ok: 'success', fail: 'error', not_configured: 'default',
  }
  const CONN_LABEL: Record<ConnResult['status'], string> = {
    ok: '正常', fail: '失败', not_configured: '未配置',
  }
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
      <Card
        title="连通性测试"
        size="small"
        style={{ marginBottom: 16 }}
        extra={<Button size="small" loading={testing} onClick={runTest}>测试 LLM / 飞书 / 数据平台</Button>}
      >
        {!conn && <Typography.Text type="secondary">点击右上角测试外部依赖连通性（只回状态，不回显密钥）。</Typography.Text>}
        <Space wrap size="middle">
          {conn?.map((c) => (
            <Tag key={c.target} color={CONN_COLOR[c.status]}>
              {c.target}：{CONN_LABEL[c.status]}
              {c.status !== 'not_configured' && ` (${c.latency_ms}ms)`}
              {c.status === 'fail' && ` — ${c.msg}`}
            </Tag>
          ))}
        </Space>
      </Card>
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

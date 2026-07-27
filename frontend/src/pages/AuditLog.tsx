/** 系统日志（F5b，仅 admin）：真人生效动作 / 配置 / 权限变更审计流（服务端筛选+翻页）。 */
import { PageContainer, ProTable, type ProColumns } from '@ant-design/pro-components'
import { Tag, Typography } from 'antd'
import { listAuditLogs, type AuditLog as Log } from '../api/admin'

const columns: ProColumns<Log>[] = [
  { title: '时间', dataIndex: 'create_time', valueType: 'dateTime', search: false, width: 170 },
  {
    title: '时间范围', dataIndex: 'created_range', valueType: 'dateTimeRange',
    hideInTable: true,
  },
  {
    title: '操作者角色', dataIndex: 'actor_role', search: false, width: 110,
    render: (_, r) => <Tag>{r.actor_role ?? '系统'}</Tag>,
  },
  { title: '操作者ID', dataIndex: 'actor_id', hideInTable: true },
  { title: '动作', dataIndex: 'action', copyable: true, width: 200 },
  { title: '摘要', dataIndex: 'summary', search: false, ellipsis: true },
  { title: '对象', dataIndex: 'target_type', search: false, width: 130 },
  {
    title: '结果', dataIndex: 'result', search: false, width: 80,
    render: (_, r) => <Tag color={r.result === 'ok' ? 'success' : 'error'}>{r.result}</Tag>,
  },
]

export default function AuditLog() {
  return (
    <PageContainer title="系统日志" subTitle="真人生效动作 / 配置 / 权限 变更审计（红线留痕，服务端筛选与翻页）">
      <ProTable<Log>
        rowKey="id"
        columns={columns}
        search={{ labelWidth: 'auto' }}
        options={{ reload: true, density: false, setting: false }}
        request={async (p) => {
          const range = p.created_range as [string, string] | undefined
          try {
            const page = await listAuditLogs({
              action: p.action as string | undefined,
              actor_id: p.actor_id as string | undefined,
              start: range?.[0],
              end: range?.[1],
              limit: p.pageSize ?? 20,
              offset: ((p.current ?? 1) - 1) * (p.pageSize ?? 20),
            })
            return { data: page.items, total: page.total, success: true }
          } catch {
            return { data: [], total: 0, success: false }
          }
        }}
        expandable={{
          rowExpandable: (r) => r.detail != null,
          expandedRowRender: (r) => (
            <Typography.Paragraph style={{ margin: 0 }}>
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: 12 }}>
                {JSON.stringify(r.detail, null, 2)}
              </pre>
            </Typography.Paragraph>
          ),
        }}
        pagination={{ pageSize: 20 }}
      />
    </PageContainer>
  )
}

/** 系统日志（F5b，仅 admin）：真人生效动作 / 配置 / 权限变更审计流。 */
import { PageContainer, ProTable, type ProColumns } from '@ant-design/pro-components'
import { Tag } from 'antd'
import { listAuditLogs, type AuditLog as Log } from '../api/admin'

const columns: ProColumns<Log>[] = [
  { title: '时间', dataIndex: 'create_time', valueType: 'dateTime', search: false, width: 170 },
  {
    title: '操作者角色', dataIndex: 'actor_role', search: false, width: 110,
    render: (_, r) => <Tag>{r.actor_role ?? '系统'}</Tag>,
  },
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
    <PageContainer title="系统日志" subTitle="真人生效动作 / 配置 / 权限 变更审计（红线留痕）">
      <ProTable<Log>
        rowKey="id"
        columns={columns}
        search={{ labelWidth: 'auto' }}
        options={{ reload: true, density: false, setting: false }}
        request={async (p) => ({
          data: await listAuditLogs({ action: p.action as string | undefined }),
          success: true,
        })}
        pagination={{ pageSize: 20 }}
      />
    </PageContainer>
  )
}

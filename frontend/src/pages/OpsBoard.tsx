/** 运营看板：上传日数据 → 查看指标 → 生成日报 / 异常检测（结果留痕）。 */
import { PageContainer, ProTable, type ProColumns } from '@ant-design/pro-components'
import { Alert, Button, Card, DatePicker, Space, Tag, Typography, Upload, message } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { useState } from 'react'
import {
  anomalyCheck,
  generateDailyReport,
  type Alert as MetricAlert,
  type TaskRecord,
} from '../api/agents'
import { listOpsDaily, uploadOpsDaily, type OpsMetric } from '../api/opsData'

const columns: ProColumns<OpsMetric>[] = [
  { title: '产品', dataIndex: 'product' },
  { title: '日活', dataIndex: 'dau' },
  { title: '新增', dataIndex: 'new_users', render: (_, r) => r.new_users ?? '-' },
  { title: '次留%', dataIndex: 'retention_d1', render: (_, r) => r.retention_d1 ?? '-' },
]

const SEV_COLOR: Record<string, string> = { critical: 'error', warning: 'warning' }

export default function OpsBoard() {
  const [date, setDate] = useState<Dayjs>(dayjs())
  const [busy, setBusy] = useState(false)
  const [report, setReport] = useState<TaskRecord | null>(null)
  const [alerts, setAlerts] = useState<MetricAlert[] | null>(null)

  const day = date.format('YYYY-MM-DD')

  const runReport = async () => {
    setBusy(true)
    setAlerts(null)
    try {
      setReport(await generateDailyReport(day))
    } catch {
      /* 拦截器已提示 */
    } finally {
      setBusy(false)
    }
  }

  const runAnomaly = async () => {
    setBusy(true)
    setReport(null)
    try {
      const res = await anomalyCheck(day)
      setAlerts(res.alerts)
      setReport(res.record)
      if (res.alerts.length === 0) message.success('未检测到异常')
    } catch {
      /* 拦截器已提示 */
    } finally {
      setBusy(false)
    }
  }

  return (
    <PageContainer title="运营看板">
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <DatePicker value={date} onChange={(d) => d && setDate(d)} allowClear={false} />
          <Upload
            accept=".xlsx"
            showUploadList={false}
            beforeUpload={(file) => {
              uploadOpsDaily(file)
                .then((r) => {
                  message.success(`已入库 ${r.upserted} 条，错误 ${r.errors.length} 条`)
                })
                .catch(() => {
                  /* 错误已由拦截器提示 */
                })
              return false
            }}
          >
            <Button>上传日数据 Excel</Button>
          </Upload>
          <Button type="primary" onClick={runReport} loading={busy}>
            生成运营日报
          </Button>
          <Button onClick={runAnomaly} loading={busy}>
            异常检测
          </Button>
        </Space>
      </Card>

      <ProTable<OpsMetric>
        rowKey="product"
        headerTitle={`${day} 运营指标`}
        search={false}
        options={false}
        pagination={false}
        params={{ day }}
        columns={columns}
        request={async () => ({ data: await listOpsDaily(day), success: true })}
      />

      {alerts && alerts.length > 0 && (
        <Card title="异常项" style={{ marginTop: 16 }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            {alerts.map((a, i) => (
              <Alert
                key={i}
                type={a.severity === 'critical' ? 'error' : 'warning'}
                message={
                  <span>
                    <Tag color={SEV_COLOR[a.severity]}>{a.product}</Tag>
                    {a.message}
                  </span>
                }
              />
            ))}
          </Space>
        </Card>
      )}

      {report && (
        <Card
          title={`AI 产出（${report.status === 'success' ? report.model_used : '失败'}）`}
          style={{ marginTop: 16 }}
        >
          <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
            {report.output_content || report.error_msg}
          </Typography.Paragraph>
        </Card>
      )}
    </PageContainer>
  )
}

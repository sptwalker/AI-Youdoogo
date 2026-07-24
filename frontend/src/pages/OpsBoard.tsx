/** 运营看板：上传日数据 → 查看指标 → 生成日报 / 异常检测（结果留痕）。 */
import { PageContainer, ProTable, type ActionType, type ProColumns } from '@ant-design/pro-components'
import { Alert, Button, Card, DatePicker, Space, Tag, Typography, Upload, message } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { useRef, useState } from 'react'
import Markdown from '../components/Markdown'
import {
  anomalyCheck,
  generateDailyReport,
  type Alert as MetricAlert,
  type TaskRecord,
} from '../api/agents'
import { listOpsDaily, syncThinkingData, uploadOpsDaily, type OpsMetric } from '../api/opsData'
import { valueForDate, type DatedResult } from '../features/ops-board/model'

const columns: ProColumns<OpsMetric>[] = [
  { title: '产品', dataIndex: 'product' },
  { title: '日活', dataIndex: 'dau' },
  { title: '新增', dataIndex: 'new_users', render: (_, r) => r.new_users ?? '-' },
  { title: '次留%', dataIndex: 'retention_d1', render: (_, r) => r.retention_d1 ?? '-' },
]

const SEV_COLOR: Record<string, string> = { critical: 'error', warning: 'warning' }

export default function OpsBoard() {
  const [date, setDate] = useState<Dayjs>(dayjs())
  const [analysisAction, setAnalysisAction] = useState<'report' | 'anomaly' | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadErrors, setUploadErrors] = useState<Array<{ row_no: number; field: string; message: string }>>([])
  const [reportResult, setReportResult] = useState<DatedResult<TaskRecord> | null>(null)
  const [alertsResult, setAlertsResult] = useState<DatedResult<MetricAlert[]> | null>(null)
  const actionRef = useRef<ActionType>(null)
  const analysisRequestRef = useRef(0)
  const analysisActionRef = useRef<'report' | 'anomaly' | null>(null)
  const syncRef = useRef(false)
  const uploadRef = useRef(false)

  const day = date.format('YYYY-MM-DD')
  const report = valueForDate(reportResult, day)
  const alerts = valueForDate(alertsResult, day)

  const selectDate = (next: Dayjs | null) => {
    if (!next) return
    analysisRequestRef.current += 1
    analysisActionRef.current = null
    setAnalysisAction(null)
    setReportResult(null)
    setAlertsResult(null)
    setDate(next)
  }

  const runSync = async () => {
    if (syncRef.current) return
    syncRef.current = true
    setSyncing(true)
    try {
      const r = await syncThinkingData(day)
      message.success(`已从 ThinkingData 拉取入库 ${r.upserted} 条`)
      actionRef.current?.reload()
    } catch {
      /* 拦截器已提示（未配置地址/密钥/SQL 时会提示）*/
    } finally {
      syncRef.current = false
      setSyncing(false)
    }
  }

  const runReport = async () => {
    if (analysisActionRef.current) return
    const requestedDay = day
    const requestId = ++analysisRequestRef.current
    analysisActionRef.current = 'report'
    setAnalysisAction('report')
    setAlertsResult(null)
    try {
      const record = await generateDailyReport(requestedDay)
      if (requestId === analysisRequestRef.current) {
        setReportResult({ date: requestedDay, value: record })
      }
    } catch {
      /* 拦截器已提示 */
    } finally {
      if (requestId === analysisRequestRef.current) {
        analysisActionRef.current = null
        setAnalysisAction(null)
      }
    }
  }

  const runAnomaly = async () => {
    if (analysisActionRef.current) return
    const requestedDay = day
    const requestId = ++analysisRequestRef.current
    analysisActionRef.current = 'anomaly'
    setAnalysisAction('anomaly')
    setReportResult(null)
    try {
      const res = await anomalyCheck(requestedDay)
      if (requestId === analysisRequestRef.current) {
        setAlertsResult({ date: requestedDay, value: res.alerts })
        setReportResult(res.record ? { date: requestedDay, value: res.record } : null)
        if (res.alerts.length === 0) message.success('未检测到异常')
      }
    } catch {
      /* 拦截器已提示 */
    } finally {
      if (requestId === analysisRequestRef.current) {
        analysisActionRef.current = null
        setAnalysisAction(null)
      }
    }
  }

  const uploadDailyData = async (file: File) => {
    if (uploadRef.current) return
    uploadRef.current = true
    setUploading(true)
    setUploadErrors([])
    try {
      const result = await uploadOpsDaily(file)
      setUploadErrors(result.errors)
      const summary = `已入库 ${result.upserted} 条，错误 ${result.errors.length} 条`
      message[result.errors.length > 0 ? 'warning' : 'success'](summary)
      actionRef.current?.reload()
    } finally {
      uploadRef.current = false
      setUploading(false)
    }
  }

  return (
    <PageContainer title="运营看板">
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <DatePicker value={date} onChange={selectDate} allowClear={false} />
          <Upload
            accept=".xlsx"
            showUploadList={false}
            beforeUpload={(file) => {
              void uploadDailyData(file).catch(() => {})
              return false
            }}
          >
            <Button loading={uploading}>上传日数据 Excel</Button>
          </Upload>
          <Button onClick={runSync} loading={syncing}>
            从 ThinkingData 拉取
          </Button>
          <Button type="primary" onClick={runReport} loading={analysisAction === 'report'} disabled={analysisAction === 'anomaly'}>
            生成运营日报
          </Button>
          <Button onClick={runAnomaly} loading={analysisAction === 'anomaly'} disabled={analysisAction === 'report'}>
            异常检测
          </Button>
        </Space>
      </Card>

      {uploadErrors.length > 0 && (
        <Alert
          type="warning"
          showIcon
          closable
          onClose={() => setUploadErrors([])}
          message={`Excel 中有 ${uploadErrors.length} 条数据未入库`}
          description={uploadErrors.slice(0, 5).map((error) => (
            <div key={`${error.row_no}-${error.field}-${error.message}`}>
              第 {error.row_no} 行 · {error.field}：{error.message}
            </div>
          ))}
          style={{ marginBottom: 16 }}
        />
      )}

      <ProTable<OpsMetric>
        rowKey="product"
        actionRef={actionRef}
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
          <Typography.Paragraph>
            <Markdown>{report.output_content || report.error_msg || ''}</Markdown>
          </Typography.Paragraph>
        </Card>
      )}
    </PageContainer>
  )
}

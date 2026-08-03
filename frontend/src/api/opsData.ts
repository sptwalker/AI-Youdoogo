/** 运营数据 API（对应后端 app/api/v1/ops_data.py）。 */
import { request } from './http'

export interface OpsMetric {
  stat_date: string
  product: string
  dau: number
  new_users: number | null
  retention_d1: number | null
}

export interface UploadResult {
  template: string
  upserted: number
  duplicates: number
  errors: Array<{ row_no: number; field: string; message: string }>
}

export function uploadOpsDaily(file: File): Promise<UploadResult> {
  const form = new FormData()
  form.append('file', file)
  return request({ method: 'POST', url: '/ops-data/daily/upload', data: form })
}

export function listOpsDaily(statDate: string): Promise<OpsMetric[]> {
  return request({ method: 'GET', url: '/ops-data/daily', params: { stat_date: statDate } })
}

/** 从 ThinkingData 拉取某日运营指标入库（地址/SQL/字段映射见系统配置，密钥见配置）。 */
export function syncThinkingData(
  statDate: string,
): Promise<{ date: string; upserted: number; source: string }> {
  return request({ method: 'POST', url: '/ops-data/sync-thinkingdata', params: { stat_date: statDate } })
}

export interface TestReadResult {
  status: 'ok' | 'fail' | 'not_configured'
  row_count: number
  sample: Array<{ product: unknown; dau: unknown; new_users: unknown }>
  msg: string
}

/** 用生效配置真跑一次 TD 查询验证能否读到数据（不落库、不回显密钥）。 */
export function testReadOpsData(statDate: string): Promise<TestReadResult> {
  return request({ method: 'GET', url: '/ops-data/test-read', params: { stat_date: statDate } })
}

// ── 运营事件命名（事件码 → 中文显示别名）──────────────────────
interface OpsEvent {
  event_code: string
  count: number
  display_name: string
}

export interface OpsEventGroup {
  view: string
  product: string
  events: OpsEvent[]
  error?: string
}

/** 列出各视图当日全部事件码+次数（合并已存别名）。 */
export function listOpsEvents(statDate: string): Promise<OpsEventGroup[]> {
  return request({ method: 'GET', url: '/ops-data/events', params: { stat_date: statDate } })
}

/** 批量保存事件中文别名（display_name 空串=清除）。 */
export function saveEventAliases(
  aliases: Array<{ view: string; event_code: string; display_name: string }>,
): Promise<{ saved: number }> {
  return request({ method: 'PUT', url: '/ops-data/event-aliases', data: { aliases } })
}

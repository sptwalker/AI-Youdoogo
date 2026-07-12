/** 运营数据 API（对应后端 app/api/v1/ops_data.py）。 */
import { request } from './client'

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

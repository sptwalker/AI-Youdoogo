import type { DataSource, OpsEventGroup } from './api'

const EVENT_KEY_SEPARATOR = '\u0000'

const SECRET_STATUS_VIEW: Record<
  DataSource['secret_status'],
  { color: string; text: string }
> = {
  not_set: { color: 'default', text: '无密钥' },
  configured: { color: 'success', text: '已配置' },
  missing: { color: 'error', text: '缺失(.env未设)' },
}

export function secretStatusView(status: DataSource['secret_status']) {
  return SECRET_STATUS_VIEW[status]
}

export function defaultEventDate(now = new Date()): string {
  const date = new Date(now)
  date.setDate(date.getDate() - 1)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function eventEditKey(view: string, eventCode: string): string {
  return `${view}${EVENT_KEY_SEPARATOR}${eventCode}`
}

export function editsFromGroups(groups: OpsEventGroup[]): Record<string, string> {
  const edits: Record<string, string> = {}
  for (const group of groups) {
    for (const event of group.events) {
      edits[eventEditKey(group.view, event.event_code)] = event.display_name
    }
  }
  return edits
}

export function aliasesFromEdits(edits: Record<string, string>) {
  return Object.entries(edits).map(([key, displayName]) => {
    const [view, eventCode] = key.split(EVENT_KEY_SEPARATOR)
    return { view, event_code: eventCode, display_name: displayName }
  })
}

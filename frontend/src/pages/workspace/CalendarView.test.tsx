// @vitest-environment jsdom

import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import dayjs, { type Dayjs } from 'dayjs'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { configurable: true, value: true })

const api = vi.hoisted(() => ({ listSchedules: vi.fn(), confirmSchedule: vi.fn() }))
vi.mock('../../api/schedule', () => ({
  listSchedules: api.listSchedules,
  confirmSchedule: api.confirmSchedule,
  SCHEDULE_STATUS: { suggested: '建议', confirmed: '已确认' },
}))
// Calendar 桩：对「本月」逐日调用 cellRender，把打点内容摊平渲染，便于断言当日是否打点。
vi.mock('antd', () => {
  const List = ({ dataSource, renderItem }: { dataSource: unknown[]; renderItem: (x: unknown) => ReactNode }) => (
    <ul>{dataSource.map((x, i) => <li key={i}>{renderItem(x)}</li>)}</ul>
  )
  List.Item = ({ actions, children }: { actions?: ReactNode; children?: ReactNode }) => <div>{children}{actions}</div>
  return {
    Badge: ({ count }: { count?: number }) => <i data-badge>{count}</i>,
    Button: ({ children, onClick }: { children?: ReactNode; onClick?: () => void }) => (
      <button onClick={onClick}>{children}</button>
    ),
    Calendar: ({ cellRender, onSelect }: {
      cellRender: (v: Dayjs) => ReactNode
      onSelect: (v: Dayjs) => void
    }) => {
      const day = dayjs('2026-08-17')
      return <div><button data-pick onClick={() => onSelect(day)}>pick-17</button><div>{cellRender(day)}</div></div>
    },
    Card: ({ title, children }: { title?: ReactNode; children?: ReactNode }) => (
      <section><h3>{title}</h3>{children}</section>
    ),
    Empty: ({ description }: { description?: ReactNode }) => <div>{description}</div>,
    List,
    Space: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
    Tag: ({ children }: { children?: ReactNode }) => <span>{children}</span>,
    message: { success: vi.fn(), error: vi.fn() },
  }
})

import CalendarView from './CalendarView'

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.clearAllMocks()
})

it('当日有日程则打点，点击列出当日日程', async () => {
  api.listSchedules.mockResolvedValue([
    { id: 's1', title: '产品评审', start_at: '2026-08-17T09:00:00', end_at: '2026-08-17T10:00:00', source: 'manual', status: 'confirmed', linked_task_id: null, create_time: '' },
  ])
  await act(async () => { root.render(<CalendarView />) })
  await act(async () => {})
  expect(container.querySelector('[data-badge]')?.textContent).toBe('1') // 当日打点

  const pick = container.querySelector('[data-pick]') as HTMLElement
  await act(async () => { pick.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
  expect(container.textContent).toContain('产品评审') // 点击后列出当日
})

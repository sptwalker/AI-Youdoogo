// @vitest-environment jsdom

import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { configurable: true, value: true })

const api = vi.hoisted(() => ({ listSchedules: vi.fn(), confirmSchedule: vi.fn() }))
vi.mock('../../api/schedule', () => ({
  listSchedules: api.listSchedules,
  confirmSchedule: api.confirmSchedule,
  SCHEDULE_STATUS: { suggested: '建议', confirmed: '已确认' },
}))
vi.mock('antd', () => ({
  Button: ({ children, onClick }: { children?: ReactNode; onClick?: () => void }) => (
    <button onClick={onClick}>{children}</button>
  ),
  Empty: ({ description }: { description?: ReactNode }) => <div>{description}</div>,
  Space: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Tag: ({ children }: { children?: ReactNode }) => <span>{children}</span>,
  Timeline: ({ items }: { items: Array<{ children: ReactNode }> }) => (
    <ul>{items.map((it, i) => <li key={i}>{it.children}</li>)}</ul>
  ),
  Typography: { Text: ({ children }: { children?: ReactNode }) => <span>{children}</span> },
  message: { success: vi.fn(), error: vi.fn() },
}))

import TimelineView from './TimelineView'

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

it('空态提示', async () => {
  api.listSchedules.mockResolvedValue([])
  await act(async () => { root.render(<TimelineView />) })
  await act(async () => {})
  expect(container.textContent).toContain('暂无日程')
})

it('列出日程且建议态可真人确认', async () => {
  api.listSchedules.mockResolvedValue([
    { id: 's1', title: '写周报', start_at: '2026-08-17T09:00:00Z', end_at: '2026-08-17T10:00:00Z', source: 'suggested', status: 'suggested', linked_task_id: null, create_time: '' },
  ])
  api.confirmSchedule.mockResolvedValue({})
  await act(async () => { root.render(<TimelineView />) })
  await act(async () => {})
  expect(container.textContent).toContain('写周报')

  expect(api.confirmSchedule).not.toHaveBeenCalled() // 未点不确认
  const btn = [...container.querySelectorAll('button')].find((b) => b.textContent === '确认生效')
  await act(async () => { btn?.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
  expect(api.confirmSchedule).toHaveBeenCalledWith('s1') // 真人点后才确认
})

// @vitest-environment jsdom

import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { configurable: true, value: true })

const api = vi.hoisted(() => ({
  getActiveFocus: vi.fn(),
  startFocus: vi.fn(),
  completeFocus: vi.fn(),
  abortFocus: vi.fn(),
}))
vi.mock('../../api/schedule', () => api)
vi.mock('antd', () => ({
  Button: ({ children, onClick }: { children?: ReactNode; onClick?: () => void }) => (
    <button onClick={onClick}>{children}</button>
  ),
  Space: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Tag: ({ children }: { children?: ReactNode }) => <span>{children}</span>,
  Typography: { Text: ({ children }: { children?: ReactNode }) => <span>{children}</span> },
  message: { success: vi.fn(), error: vi.fn() },
}))

import FocusTimer from './FocusTimer'

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

const click = async (text: string) => {
  const btn = [...container.querySelectorAll('button')].find((b) => b.textContent?.includes(text))
  await act(async () => { btn?.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
}

it('无进行中会话时可开始专注', async () => {
  api.getActiveFocus.mockResolvedValue(null)
  api.startFocus.mockResolvedValue({ id: 'f1', start_at: '2026-08-17T09:00:00Z', planned_minutes: 25, status: 'active' })
  await act(async () => { root.render(<FocusTimer />) })
  await act(async () => {})
  expect(container.textContent).toContain('开始专注')

  await click('开始专注')
  expect(api.startFocus).toHaveBeenCalledWith(25)
  expect(container.textContent).toContain('专注中') // 开始后切进行中态
})

it('进行中会话可完成并回到可开始态', async () => {
  api.getActiveFocus.mockResolvedValue({ id: 'f1', start_at: '2026-08-17T09:00:00Z', planned_minutes: 25, status: 'active' })
  api.completeFocus.mockResolvedValue({ id: 'f1', status: 'completed' })
  await act(async () => { root.render(<FocusTimer />) })
  await act(async () => {})
  expect(container.textContent).toContain('专注中')

  await click('完成')
  expect(api.completeFocus).toHaveBeenCalledWith('f1')
  expect(container.textContent).toContain('开始专注') // 完成后回到可开始
})

// @vitest-environment jsdom

import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { configurable: true, value: true })

const api = vi.hoisted(() => ({
  listMeetings: vi.fn(),
  getMeeting: vi.fn(),
  convertResolution: vi.fn(),
  confirmResolution: vi.fn(),
}))
vi.mock('../api/meetings', () => ({
  ...api,
  MEETING_STATUS: { closed: '已闭会' },
  // 以下仅为满足 import 绑定，测试路径不会触发。
  aiSpeak: vi.fn(), aiVote: vi.fn(), createMeeting: vi.fn(), createResolution: vi.fn(),
  discuss: vi.fn(), generateMinutes: vi.fn(), getTally: vi.fn(), listVoteSubjects: vi.fn().mockResolvedValue([]),
  setMeetingStatus: vi.fn(), vote: vi.fn(),
}))
vi.mock('react-router-dom', () => ({ useOutletContext: () => ({ me: { role_code: 'admin' } }) }))
vi.mock('../components/Markdown', () => ({ default: ({ children }: { children?: ReactNode }) => <div>{children}</div> }))

// ProTable 桩：拉取 request().data，逐行渲染各列 render（含「进入」链接），驱动真实打开逻辑。
vi.mock('@ant-design/pro-components', async () => {
  const { useEffect, useState } = await import('react')
  return {
    PageContainer: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
    ProTable: ({ request, columns }: { request: () => Promise<{ data: unknown[] }>; columns: Array<{ dataIndex?: string; render?: (v: unknown, row: unknown) => ReactNode }> }) => {
      const [rows, setRows] = useState<Record<string, unknown>[]>([])
      // eslint-disable-next-line react-hooks/exhaustive-deps
      useEffect(() => { void request().then((r) => setRows(r.data as Record<string, unknown>[])) }, [])
      return <table><tbody>{rows.map((row, i) => (
        <tr key={i}>{columns.map((c, j) => <td key={j}>{c.render ? c.render(undefined, row) : String(row[c.dataIndex ?? ''] ?? '')}</td>)}</tr>
      ))}</tbody></table>
    },
    ModalForm: () => null,
    ProFormText: () => null,
  }
})
vi.mock('antd', () => {
  const List = ({ dataSource, renderItem, locale }: { dataSource: unknown[]; renderItem: (x: unknown) => ReactNode; locale?: { emptyText?: ReactNode } }) =>
    dataSource.length > 0 ? <ul>{dataSource.map((x, i) => <li key={i}>{renderItem(x)}</li>)}</ul> : <div>{locale?.emptyText}</div>
  List.Item = ({ actions, children }: { actions?: ReactNode; children?: ReactNode }) => <div>{children}{actions}</div>
  const Space = ({ children }: { children?: ReactNode }) => <div>{children}</div>
  Space.Compact = Space
  return {
    Drawer: ({ open, title, children }: { open?: boolean; title?: ReactNode; children?: ReactNode }) => (open ? <div>{title}{children}</div> : null),
    Card: ({ title, extra, children }: { title?: ReactNode; extra?: ReactNode; children?: ReactNode }) => <section>{title}{extra}{children}</section>,
    Button: ({ children, onClick, disabled }: { children?: ReactNode; onClick?: () => void; disabled?: boolean }) => <button onClick={onClick} disabled={disabled}>{children}</button>,
    List, Space,
    Tag: ({ children }: { children?: ReactNode }) => <span>{children}</span>,
    Input: (p: Record<string, unknown>) => <input value={(p.value as string) ?? ''} readOnly />,
    Popconfirm: ({ children }: { children?: ReactNode }) => <>{children}</>,
    AutoComplete: () => <input />,
    message: { success: vi.fn(), error: vi.fn(), loading: vi.fn(), destroy: vi.fn() },
  }
})

import Meetings from './Meetings'

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

it('已确认决议的「转任务卡」仅在真人点击后才调用（红线：AI 不自动执行）', async () => {
  api.listMeetings.mockResolvedValue([{ id: 'm1', title: '周会', status: 'closed', create_time: '' }])
  api.getMeeting.mockResolvedValue({
    meeting: { id: 'm1', title: '周会', status: 'closed', summary: '', create_time: '' },
    discussions: [],
    resolutions: [{ id: 'r1', content: '决议A', is_confirmed: true, converted_task_id: null }],
  })
  api.convertResolution.mockResolvedValue({})

  await act(async () => { root.render(<Meetings />) })
  await act(async () => {}) // request() 落地

  const open = [...container.querySelectorAll('a')].find((a) => a.textContent === '进入')
  await act(async () => { open?.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
  expect(container.textContent).toContain('决议A') // 抽屉已打开

  const convertBtn = [...container.querySelectorAll('button')].find((b) => b.textContent === '转任务卡')
  expect(convertBtn).toBeTruthy()
  expect(api.convertResolution).not.toHaveBeenCalled() // 未点不转

  await act(async () => { convertBtn?.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
  expect(api.convertResolution).toHaveBeenCalledWith('r1') // 真人点后才转任务卡
})

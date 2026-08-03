// @vitest-environment jsdom

import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/http'
import AppLayout from './AppLayout'

Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', {
  configurable: true,
  value: true,
})

const authMocks = vi.hoisted(() => ({ fetchMe: vi.fn() }))

vi.mock('../api/auth', () => ({
  fetchMe: authMocks.fetchMe,
  ROLE_LABELS: { admin: '超级管理员', executive: '高管', member: '成员' },
}))

vi.mock('@ant-design/icons', () => ({ LogoutOutlined: () => null }))

vi.mock('@ant-design/pro-components', () => ({
  ProLayout: ({ avatarProps, children }: {
    avatarProps: { render: (item: unknown, dom: ReactNode) => ReactNode }
    children?: ReactNode
  }) => (
    <div>
      {avatarProps.render(null, <span>avatar</span>)}
      {children}
    </div>
  ),
}))

vi.mock('antd', () => ({
  Button: ({ children, onClick }: { children?: ReactNode; onClick?: () => void }) => (
    <button onClick={onClick}>{children}</button>
  ),
  Dropdown: ({ menu, children }: {
    menu: { items?: Array<{ onClick?: () => void }> }
    children?: ReactNode
  }) => (
    <div>
      <button onClick={menu.items?.[0]?.onClick}>dropdown-logout</button>
      {children}
    </div>
  ),
  Result: ({ extra }: { extra?: ReactNode }) => <div>{extra}</div>,
  Spin: () => <div>loading</div>,
}))

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  authMocks.fetchMe.mockResolvedValue({
    id: 'user-1',
    username: 'alice',
    real_name: 'Alice',
    role_code: 'member',
    department_id: null,
    is_active: true,
    create_time: '2026-01-01T00:00:00Z',
  })
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})

afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  localStorage.clear()
  sessionStorage.clear()
  vi.clearAllMocks()
})

async function renderLayout() {
  const router = createMemoryRouter([
    { path: '/login', element: <output>login</output> },
    { path: '*', element: <AppLayout /> },
  ], { initialEntries: ['/'] })
  await act(async () => {
    root.render(<RouterProvider router={router} />)
  })
  await vi.waitFor(() => expect(container.textContent).toContain('dropdown-logout'))
}

describe('AppLayout logout', () => {
  it('clears both token stores before navigating to login', async () => {
    localStorage.setItem(TOKEN_KEY, 'remembered-token')
    sessionStorage.setItem(TOKEN_KEY, 'session-token')
    await renderLayout()

    const logoutButton = Array.from(container.querySelectorAll('button'))
      .find((button) => button.textContent === 'dropdown-logout')
    expect(logoutButton).toBeDefined()
    await act(async () => logoutButton?.click())

    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
    expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull()
    expect(container.querySelector('output')?.textContent).toBe('login')
  })
})

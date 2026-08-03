// @vitest-environment jsdom

import { act, type ReactElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { TOKEN_KEY } from '../api/http'
import RequireAuth from './RequireAuth'

Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', {
  configurable: true,
  value: true,
})

let container: HTMLDivElement
let root: Root

function LocationProbe() {
  const location = useLocation()
  return <output>{`${location.pathname}${location.search}`}</output>
}

async function renderAt(path: string, protectedContent: ReactElement) {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/login" element={<LocationProbe />} />
          <Route path="*" element={<RequireAuth>{protectedContent}</RequireAuth>} />
        </Routes>
      </MemoryRouter>,
    )
  })
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})

afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  localStorage.clear()
  sessionStorage.clear()
})

describe('RequireAuth', () => {
  it('redirects anonymous users and preserves the complete intended page', async () => {
    await renderAt('/system-config?tab=security', <div>protected settings</div>)

    expect(container.textContent).not.toContain('protected settings')
    expect(container.querySelector('output')?.textContent).toBe(
      '/login?return_to=%2Fsystem-config%3Ftab%3Dsecurity',
    )
  })

  it('renders the protected route when a token is present', async () => {
    localStorage.setItem(TOKEN_KEY, 'valid-token')

    await renderAt('/system-config?tab=security', <div>protected settings</div>)

    expect(container.textContent).toContain('protected settings')
    expect(container.querySelector('output')).toBeNull()
  })

  it('renders the protected route when the token is scoped to this browser session', async () => {
    sessionStorage.setItem(TOKEN_KEY, 'session-token')

    await renderAt('/system-config?tab=security', <div>protected settings</div>)

    expect(container.textContent).toContain('protected settings')
    expect(container.querySelector('output')).toBeNull()
  })
})

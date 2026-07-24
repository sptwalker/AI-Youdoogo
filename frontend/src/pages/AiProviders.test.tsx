// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as providersApi from '../api/aiProviders'
import type { AiProvider } from '../api/aiProviders'
import AiProviders from './AiProviders'

Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', {
  configurable: true,
  value: true,
})

const getComputedStyleWithoutPseudoElements = window.getComputedStyle.bind(window)
Object.defineProperty(window, 'getComputedStyle', {
  configurable: true,
  value: (element: Element) => getComputedStyleWithoutPseudoElements(element),
})

Object.defineProperty(window, 'matchMedia', {
  configurable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(globalThis, 'ResizeObserver', {
  configurable: true,
  value: ResizeObserverStub,
})

const provider: AiProvider & { api_key: string } = {
  id: 'provider-1',
  name: 'DeepSeek 主力',
  tier: 'daily',
  base_url: 'https://api.deepseek.com',
  model: 'deepseek-chat',
  api_key_hint: '••••1234',
  api_key_set: true,
  api_key: 'stored-provider-secret',
  is_primary: true,
  is_active: true,
  last_test_status: 'ok',
  last_test_at: '2026-07-24T00:00:00Z',
  last_test_latency_ms: 86,
  last_test_msg: null,
}

let container: HTMLDivElement
let root: Root

async function flushUi() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

function clickByText(text: string) {
  const target = [...document.querySelectorAll<HTMLElement>('a, button')]
    .find((element) => element.textContent?.trim() === text)
  if (!target) throw new Error(`Could not find clickable text: ${text}`)
  target.click()
}

beforeEach(() => {
  vi.spyOn(providersApi, 'listProviders').mockResolvedValue([provider])
  vi.spyOn(providersApi, 'updateProvider').mockResolvedValue({ id: provider.id })
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})

afterEach(async () => {
  await act(async () => root.unmount())
  document.body.replaceChildren()
  vi.restoreAllMocks()
})

describe('AiProviders', () => {
  it('never echoes the stored secret and preserves it when an edit is saved blank', async () => {
    await act(async () => root.render(<AiProviders />))
    await flushUi()

    expect(document.body.textContent).toContain(provider.api_key_hint)
    expect(document.body.textContent).not.toContain('stored-provider-secret')

    await act(async () => clickByText('编辑'))
    await flushUi()

    const secretInput = document.querySelector<HTMLInputElement>('input[type="password"]')
    expect(secretInput).not.toBeNull()
    expect(secretInput?.value).toBe('')

    await act(async () => clickByText('确 定'))
    await flushUi()

    expect(providersApi.updateProvider).toHaveBeenCalledWith(provider.id, {
      name: provider.name,
      tier: provider.tier,
      base_url: provider.base_url,
      model: provider.model,
    })
    expect(providersApi.listProviders).toHaveBeenCalledTimes(2)
  })
})

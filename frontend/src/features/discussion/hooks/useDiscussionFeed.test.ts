// @vitest-environment jsdom

import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DiscussionWorkspaceApi, Message } from '../api'
import type { DiscussionFeed } from './useDiscussionFeed'
import { useDiscussionFeed } from './useDiscussionFeed'

Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', {
  configurable: true,
  value: true,
})

function message(id: string, channelId: string): Message {
  return {
    id,
    channel_id: channelId,
    speaker_type: 'human',
    speaker_id: 'human-1',
    speaker_name: 'Alice',
    content: id,
    mentioned_agent_ids: [],
    ai_source_record_id: null,
    ref_type: null,
    ref_id: null,
    create_time: '',
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

function createApi(overrides: Partial<DiscussionWorkspaceApi> = {}) {
  let onEvent: ((event: string, data: Record<string, unknown>) => void) | undefined
  let onState: ((state: 'connecting' | 'connected' | 'disconnected') => void) | undefined
  const cancel = vi.fn() as unknown as ReturnType<DiscussionWorkspaceApi['subscribeRealtime']>
  cancel.restart = vi.fn()
  const channels = [
    {
      id: 'channel-a', name: 'A', department_id: null, default_agent_id: null,
      creator_id: 'owner-1', is_archived: false, create_time: '', unread: 3,
    },
    {
      id: 'channel-b', name: 'B', department_id: null, default_agent_id: null,
      creator_id: 'owner-2', is_archived: false, create_time: '', unread: 0,
    },
  ]
  const api = {
    listAgents: vi.fn().mockResolvedValue([]),
    listColleagues: vi.fn().mockResolvedValue([]),
    listMembers: vi.fn().mockResolvedValue([]),
    addMembers: vi.fn().mockResolvedValue({ added: 0 }),
    removeMember: vi.fn().mockResolvedValue(null),
    disbandChannel: vi.fn().mockResolvedValue(null),
    listMessages: vi.fn().mockResolvedValue([]),
    markRead: vi.fn().mockResolvedValue(null),
    postMessage: vi.fn().mockResolvedValue(undefined),
    uploadAttachment: vi.fn(),
    downloadAttachment: vi.fn().mockResolvedValue(undefined),
    listChannels: vi.fn().mockResolvedValue(channels),
    createChannel: vi.fn(),
    subscribeRealtime: vi.fn((eventHandler, stateHandler) => {
      onEvent = eventHandler
      onState = stateHandler
      return cancel
    }),
    promoteMessage: vi.fn(),
    ...overrides,
  } satisfies DiscussionWorkspaceApi
  return {
    api,
    cancel,
    emitMessage: (incoming: Message) => onEvent?.('message', incoming as unknown as Record<string, unknown>),
    emitState: (state: 'connecting' | 'connected' | 'disconnected') => onState?.(state),
  }
}

interface FeedProps {
  activeChannelId: string | null
  api: DiscussionWorkspaceApi
}

async function renderFeed(initialProps: FeedProps) {
  const root = createRoot(document.createElement('div'))
  let current: DiscussionFeed | undefined

  function Probe(props: FeedProps) {
    current = useDiscussionFeed(props)
    return null
  }

  const render = async (props: FeedProps) => {
    await act(async () => {
      root.render(createElement(Probe, props))
      await Promise.resolve()
      await Promise.resolve()
    })
  }

  await render(initialProps)
  return {
    get current() {
      if (!current) throw new Error('Discussion feed did not render')
      return current
    },
    rerender: render,
    unmount: async () => { await act(async () => root.unmount()) },
  }
}

async function flushEffects() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

afterEach(() => {
  vi.useRealTimers()
})

describe('useDiscussionFeed', () => {
  it('owns realtime delivery, read acknowledgement, polling transitions, refresh, and cleanup', async () => {
    vi.useFakeTimers()
    const { api, cancel, emitMessage, emitState } = createApi({
      listMessages: vi.fn().mockResolvedValue([message('initial', 'channel-a')]),
    })
    const rendered = await renderFeed({ activeChannelId: 'channel-a', api })
    await flushEffects()

    expect(api.listChannels).toHaveBeenCalledTimes(1)
    expect(api.listMessages).toHaveBeenCalledTimes(1)
    expect(api.markRead).toHaveBeenCalledWith(
      'channel-a', expect.objectContaining({ silent: true }),
    )
    expect(rendered.current.activeSession.messages.map((item) => item.id)).toEqual(['initial'])
    expect(rendered.current.channels.find((channel) => channel.id === 'channel-a')?.unread).toBe(0)

    await act(async () => {
      emitMessage(message('background', 'channel-b'))
      emitMessage(message('live-1', 'channel-a'))
      emitMessage(message('live-2', 'channel-a'))
    })
    expect(rendered.current.channels.find((channel) => channel.id === 'channel-b')?.unread).toBe(1)
    expect(rendered.current.activeSession.messages.map((item) => item.id)).toEqual([
      'initial', 'live-1', 'live-2',
    ])

    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(api.listChannels).toHaveBeenCalledTimes(2)
    expect(api.listMessages).toHaveBeenCalledTimes(2)

    await act(async () => emitState('connected'))
    await flushEffects()
    expect(api.listChannels).toHaveBeenCalledTimes(3)
    expect(api.listMessages).toHaveBeenCalledTimes(3)
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(api.listChannels).toHaveBeenCalledTimes(3)
    expect(api.listMessages).toHaveBeenCalledTimes(3)
    await act(async () => { await vi.advanceTimersByTimeAsync(55000) })
    expect(api.listChannels).toHaveBeenCalledTimes(4)
    expect(api.listMessages).toHaveBeenCalledTimes(3)

    await act(async () => { await rendered.current.refreshChannels(true) })
    expect(cancel.restart).toHaveBeenCalled()

    const channelSignal = vi.mocked(api.listChannels).mock.calls.at(-2)?.[0]?.signal
    const messageSignal = vi.mocked(api.listMessages).mock.calls.at(-1)?.[1]?.signal
    await rendered.unmount()
    expect(cancel).toHaveBeenCalledOnce()
    expect(channelSignal?.aborted).toBe(true)
    expect(messageSignal?.aborted).toBe(true)
  })

  it('ignores a late previous-channel refresh and clears the visible session on deselection', async () => {
    const firstRefresh = deferred<Message[]>()
    const { api } = createApi({
      listMessages: vi.fn((channelId: string) => (
        channelId === 'channel-a'
          ? firstRefresh.promise
          : Promise.resolve([message('channel-b-message', 'channel-b')])
      )),
    })
    const rendered = await renderFeed({ activeChannelId: 'channel-a', api })
    const firstSignal = vi.mocked(api.listMessages).mock.calls[0]?.[1]?.signal

    await rendered.rerender({ activeChannelId: 'channel-b', api })
    await flushEffects()
    expect(firstSignal?.aborted).toBe(true)
    expect(rendered.current.activeSession.messages.map((item) => item.id))
      .toEqual(['channel-b-message'])

    firstRefresh.resolve([message('late-channel-a-message', 'channel-a')])
    await flushEffects()
    expect(rendered.current.activeSession.messages.map((item) => item.id))
      .toEqual(['channel-b-message'])

    await rendered.rerender({ activeChannelId: null, api })
    expect(rendered.current.activeSession.messages).toEqual([])
    await rendered.unmount()
  })

  it('forces a realtime restart even when an explicit channel refresh fails', async () => {
    const listChannels = vi.fn()
      .mockResolvedValueOnce([])
      .mockRejectedValueOnce(new Error('refresh failed'))
    const { api, cancel } = createApi({ listChannels })
    const rendered = await renderFeed({ activeChannelId: null, api })
    await flushEffects()

    await expect(rendered.current.refreshChannels(true)).rejects.toThrow('refresh failed')
    expect(cancel.restart).toHaveBeenCalledOnce()
    await rendered.unmount()
  })
})

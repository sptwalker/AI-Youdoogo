// @vitest-environment jsdom

import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it, vi } from 'vitest'
import type { DiscussionMember, GroupChatApi } from '../api'
import { MAX_ATTACHMENT_BYTES } from '../model'
import type { AdvisorComposerState } from './useAdvisorComposer'
import { useAdvisorComposer } from './useAdvisorComposer'
import type { ChannelMembersState } from './useChannelMembers'
import { useChannelMembers } from './useChannelMembers'
import type { MessageComposerState } from './useMessageComposer'
import { useMessageComposer } from './useMessageComposer'

Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', {
  configurable: true,
  value: true,
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

function createApi(overrides: Partial<GroupChatApi> = {}): GroupChatApi {
  return {
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
    ...overrides,
  }
}

async function flushEffects() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

interface ComposerProps {
  channelId: string
  members: DiscussionMember[]
  ingestStreamEvent(event: string, data: Record<string, unknown>): void
  onFileTooLarge(): void
  onUploadFailed(): void
  api: GroupChatApi
}

async function renderComposer(props: ComposerProps) {
  const root = createRoot(document.createElement('div'))
  let current: MessageComposerState | undefined

  function Probe(input: ComposerProps) {
    current = useMessageComposer(input)
    return null
  }

  await act(async () => root.render(createElement(Probe, props)))
  return {
    get current() {
      if (!current) throw new Error('Composer hook did not render')
      return current
    },
    unmount: async () => { await act(async () => root.unmount()) },
  }
}

describe('useMessageComposer', () => {
  it('blocks oversized files and retains successful attachment metadata', async () => {
    const uploaded = {
      type: 'file' as const,
      name: 'brief.pdf',
      storage_path: 'chat/brief.pdf',
      size: 64,
    }
    const api = createApi({ uploadAttachment: vi.fn().mockResolvedValue(uploaded) })
    const onFileTooLarge = vi.fn()
    const onUploadFailed = vi.fn()
    const rendered = await renderComposer({
      channelId: 'channel-a',
      members: [],
      ingestStreamEvent: vi.fn(),
      onFileTooLarge,
      onUploadFailed,
      api,
    })

    await act(async () => {
      await rendered.current.upload({ size: MAX_ATTACHMENT_BYTES + 1 } as File)
    })
    expect(onFileTooLarge).toHaveBeenCalledOnce()
    expect(api.uploadAttachment).not.toHaveBeenCalled()

    await act(async () => {
      await rendered.current.upload(new File(['content'], 'brief.pdf'))
    })
    expect(rendered.current.pendingAttachments).toEqual([uploaded])
    expect(onUploadFailed).not.toHaveBeenCalled()
    await rendered.unmount()
  })

  it('clears the submitted draft and prevents concurrent duplicate sends', async () => {
    const posted = deferred<void>()
    const api = createApi({ postMessage: vi.fn(() => posted.promise) })
    const members: DiscussionMember[] = [
      { member_type: 'human', member_id: 'human-1', member_name: 'Alice' },
      { member_type: 'ai', member_id: 'ai-1', member_name: 'Planner' },
    ]
    const rendered = await renderComposer({
      channelId: 'channel-a',
      members,
      ingestStreamEvent: vi.fn(),
      onFileTooLarge: vi.fn(),
      onUploadFailed: vi.fn(),
      api,
    })

    await act(async () => {
      rendered.current.setText('review this')
      rendered.current.setMentions(['human-1', 'ai-1'])
    })
    await act(async () => {
      void rendered.current.send()
      void rendered.current.send()
      await Promise.resolve()
    })

    expect(api.postMessage).toHaveBeenCalledOnce()
    expect(api.postMessage).toHaveBeenCalledWith(
      'channel-a',
      '@Alice @Planner review this',
      ['ai-1'],
      expect.any(Function),
      [],
    )
    expect(rendered.current.text).toBe('')
    expect(rendered.current.mentions).toEqual([])
    expect(rendered.current.sending).toBe(true)

    posted.resolve()
    await flushEffects()
    expect(rendered.current.sending).toBe(false)
    await rendered.unmount()
  })
})

describe('useAdvisorComposer', () => {
  it('preserves the draft on failure, clears streaming state, and limits AI mentions', async () => {
    const clearStreamingMessage = vi.fn()
    const ingestStreamEvent = vi.fn()
    const api = createApi({ postMessage: vi.fn().mockRejectedValue(new Error('stream failed')) })
    const root = createRoot(document.createElement('div'))
    let current: AdvisorComposerState | undefined

    function Probe() {
      current = useAdvisorComposer({
        channelId: 'channel-a', ingestStreamEvent, clearStreamingMessage, api,
      })
      return null
    }

    await act(async () => root.render(createElement(Probe)))
    await act(async () => {
      current?.setText('  review this  ')
      current?.setMentions(['ai-1', 'ai-2', 'ai-3', 'ai-4'])
    })
    await act(async () => { await current?.send() })

    expect(api.postMessage).toHaveBeenCalledWith(
      'channel-a', 'review this', ['ai-1', 'ai-2', 'ai-3'], ingestStreamEvent,
    )
    expect(clearStreamingMessage).toHaveBeenCalledOnce()
    expect(current?.text).toBe('  review this  ')
    expect(current?.mentions).toEqual(['ai-1', 'ai-2', 'ai-3', 'ai-4'])
    await act(async () => root.unmount())
  })

  it('clears the draft only after a successful send', async () => {
    const api = createApi()
    const root = createRoot(document.createElement('div'))
    let current: AdvisorComposerState | undefined

    function Probe() {
      current = useAdvisorComposer({
        channelId: 'channel-a',
        ingestStreamEvent: vi.fn(),
        clearStreamingMessage: vi.fn(),
        api,
      })
      return null
    }

    await act(async () => root.render(createElement(Probe)))
    await act(async () => {
      current?.setText('hello')
      current?.setMentions(['ai-1'])
    })
    await act(async () => { await current?.send() })
    expect(current?.text).toBe('')
    expect(current?.mentions).toEqual([])
    await act(async () => root.unmount())
  })
})

interface MembersProps {
  channelId: string
  onMembershipChange(): void
  api: GroupChatApi
}

async function renderMembers(initialProps: MembersProps) {
  const root = createRoot(document.createElement('div'))
  let current: ChannelMembersState | undefined

  function Probe(props: MembersProps) {
    current = useChannelMembers(props)
    return null
  }

  const render = async (props: MembersProps) => {
    await act(async () => {
      root.render(createElement(Probe, props))
      await Promise.resolve()
      await Promise.resolve()
    })
  }

  await render(initialProps)
  return {
    get current() {
      if (!current) throw new Error('Membership hook did not render')
      return current
    },
    rerender: render,
    unmount: async () => { await act(async () => root.unmount()) },
  }
}

describe('useChannelMembers', () => {
  it('aborts stale channel membership loads and keeps the newest channel state', async () => {
    const firstLoad = deferred<DiscussionMember[]>()
    const channelBMember: DiscussionMember = {
      member_type: 'human', member_id: 'human-b', member_name: 'Channel B',
    }
    const api = createApi({
      listMembers: vi.fn((channelId: string) => (
        channelId === 'channel-a' ? firstLoad.promise : Promise.resolve([channelBMember])
      )),
    })
    const onMembershipChange = vi.fn()
    const rendered = await renderMembers({ channelId: 'channel-a', onMembershipChange, api })
    const firstSignal = vi.mocked(api.listMembers).mock.calls[0]?.[1]?.signal

    await rendered.rerender({ channelId: 'channel-b', onMembershipChange, api })
    await flushEffects()
    expect(firstSignal?.aborted).toBe(true)
    expect(rendered.current.members).toEqual([channelBMember])

    firstLoad.resolve([{
      member_type: 'human', member_id: 'human-a', member_name: 'Late Channel A',
    }])
    await flushEffects()
    expect(rendered.current.members).toEqual([channelBMember])
    await rendered.unmount()
  })

  it('mutates membership, refreshes, and notifies the parent exactly once per change', async () => {
    const api = createApi()
    const onMembershipChange = vi.fn()
    const rendered = await renderMembers({ channelId: 'channel-a', onMembershipChange, api })
    await flushEffects()

    await act(async () => {
      await rendered.current.addMembers([{
        member_type: 'ai', member_id: 'ai-1', member_name: 'Planner',
      }])
    })
    expect(api.addMembers).toHaveBeenCalledOnce()
    expect(onMembershipChange).toHaveBeenCalledTimes(1)

    await act(async () => {
      await rendered.current.removeMember({
        member_type: 'human', member_id: 'human-2', member_name: 'Colleague',
      })
    })
    expect(api.removeMember).toHaveBeenCalledWith('channel-a', 'human', 'human-2')
    expect(onMembershipChange).toHaveBeenCalledTimes(2)
    expect(vi.mocked(api.listMembers).mock.calls.length).toBeGreaterThanOrEqual(3)
    expect(api.listAgents).not.toHaveBeenCalled()
    await rendered.unmount()
  })
})

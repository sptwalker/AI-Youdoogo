// @vitest-environment jsdom

import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it, vi } from 'vitest'
import * as desktopApi from '../../api/desktop'
import type { Attachment, DesktopMessage } from '../../api/desktop'
import AssistantChatCard from './AssistantChatCard'
import { parseMessageTime, shouldShowTimeSeparator, sortPinnedMessages } from './assistantChatModel'

Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', {
  configurable: true,
  value: true,
})

function pinnedMessage(): DesktopMessage {
  return {
    id: '7',
    speaker_type: 'ai',
    speaker_agent_id: 'a',
    speaker_name: '助理',
    content: '重要结论',
    create_time: '2026-07-24T08:00:00Z',
    reply_to_message_id: null,
    reply_preview: null,
    attachments: [],
    is_pinned: true,
    pinned_at: '2026-07-24T08:05:00Z',
    pinned_by_user_id: 'u',
  }
}

function imageAttachment(): Attachment {
  return {
    name: 'diagram.png',
    storage_path: 'desktop-chat/demo/diagram.png',
    size: 123,
    type: 'image',
  }
}

function imageMessage(createTime = ''): DesktopMessage {
  return {
    id: 'img-1',
    speaker_type: 'user',
    speaker_agent_id: null,
    speaker_name: '我',
    content: '[附件]',
    create_time: createTime,
    reply_to_message_id: null,
    reply_preview: null,
    attachments: [imageAttachment()],
    is_pinned: false,
    pinned_at: null,
    pinned_by_user_id: null,
  }
}

describe('AssistantChatCard time helpers', () => {
  it('parses valid timestamps and rejects empty or invalid values', () => {
    expect(parseMessageTime('2026-07-24T08:00:00Z')).toBeInstanceOf(Date)
    expect(parseMessageTime('')).toBeNull()
    expect(parseMessageTime('not-a-date')).toBeNull()
  })

  it('shows a separator for the first persisted message', () => {
    expect(shouldShowTimeSeparator(undefined, '2026-07-24T08:00:00Z')).toBe(true)
  })

  it('does not show a separator when the gap is exactly 3 minutes or less', () => {
    expect(shouldShowTimeSeparator('2026-07-24T08:00:00Z', '2026-07-24T08:02:59Z')).toBe(false)
    expect(shouldShowTimeSeparator('2026-07-24T08:00:00Z', '2026-07-24T08:03:00Z')).toBe(false)
  })

  it('shows a separator when the gap exceeds 3 minutes', () => {
    expect(shouldShowTimeSeparator('2026-07-24T08:00:00Z', '2026-07-24T08:03:01Z')).toBe(true)
  })

  it('skips separators when current or previous timestamps are not persisted yet', () => {
    expect(shouldShowTimeSeparator('', '2026-07-24T08:03:01Z')).toBe(false)
    expect(shouldShowTimeSeparator('2026-07-24T08:00:00Z', '')).toBe(false)
  })
})

describe('sortPinnedMessages', () => {
  it('keeps only pinned messages and sorts latest pinned first', () => {
    const sorted = sortPinnedMessages([
      {
        id: '1',
        speaker_type: 'user',
        speaker_agent_id: null,
        speaker_name: '我',
        content: '未置顶',
        create_time: '2026-07-24T08:00:00Z',
        reply_to_message_id: null,
        reply_preview: null,
        attachments: [],
        is_pinned: false,
        pinned_at: null,
        pinned_by_user_id: null,
      },
      {
        id: '2',
        speaker_type: 'ai',
        speaker_agent_id: 'a',
        speaker_name: '助理',
        content: '较早置顶',
        create_time: '2026-07-24T08:01:00Z',
        reply_to_message_id: null,
        reply_preview: null,
        attachments: [],
        is_pinned: true,
        pinned_at: '2026-07-24T08:05:00Z',
        pinned_by_user_id: 'u',
      },
      {
        id: '3',
        speaker_type: 'ai',
        speaker_agent_id: 'b',
        speaker_name: '专家',
        content: '最新置顶',
        create_time: '2026-07-24T08:02:00Z',
        reply_to_message_id: null,
        reply_preview: null,
        attachments: [],
        is_pinned: true,
        pinned_at: '2026-07-24T08:06:00Z',
        pinned_by_user_id: 'u',
      },
    ])

    expect(sorted.map((message) => message.id)).toEqual(['3', '2'])
  })
})

describe('pinned banner', () => {
  it('unpins from the banner via onPinToggle', async () => {
    const onPinToggle = vi.fn().mockResolvedValue(undefined)
    const host = document.createElement('div')
    document.body.appendChild(host)
    const mounted = createRoot(host)
    await act(async () => mounted.render(createElement(AssistantChatCard, {
      addable: [],
      addAgentIds: [],
      assistant: { id: 'x', name: '助理' },
      chatBoxRef: { current: null },
      chatInput: '',
      chatMessages: [pinnedMessage()],
      chatSending: false,
      chatUploading: false,
      pendingAttachments: [],
      replyingTo: null,
      orchestration: null,
      onAcceptStep: vi.fn(),
      onCancelReply: vi.fn(),
      onDownloadAttachment: vi.fn(),
      onPinToggle,
      onRemoveAttachment: vi.fn(),
      onReply: vi.fn(),
      onSend: vi.fn(),
      onUpload: vi.fn(),
      setAddAgentIds: vi.fn(),
      setChatInput: vi.fn(),
      setOrchestration: vi.fn(),
    })))

    const cancel = host.querySelector('a[title="取消置顶"]') as HTMLElement | null
    expect(cancel).not.toBeNull()
    await act(async () => cancel!.click())

    expect(onPinToggle).toHaveBeenCalledTimes(1)
    expect(onPinToggle.mock.calls[0][0]).toMatchObject({ id: '7', is_pinned: true })
    await act(async () => mounted.unmount())
    host.remove()
  })
})

describe('inline image preview gating', () => {
  it('waits for a persisted message before fetching the protected image blob', async () => {
    const fetchDesktopAttachment = vi
      .spyOn(desktopApi, 'fetchDesktopAttachment')
      .mockResolvedValue(new Blob(['x'], { type: 'image/png' }))

    const host = document.createElement('div')
    document.body.appendChild(host)
    const mounted = createRoot(host)

    await act(async () => mounted.render(createElement(AssistantChatCard, {
      addable: [],
      addAgentIds: [],
      assistant: { id: 'x', name: '助理' },
      chatBoxRef: { current: null },
      chatInput: '',
      chatMessages: [imageMessage('')],
      chatSending: false,
      chatUploading: false,
      pendingAttachments: [],
      replyingTo: null,
      orchestration: null,
      onAcceptStep: vi.fn(),
      onCancelReply: vi.fn(),
      onDownloadAttachment: vi.fn(),
      onPinToggle: vi.fn(),
      onRemoveAttachment: vi.fn(),
      onReply: vi.fn(),
      onSend: vi.fn(),
      onUpload: vi.fn(),
      setAddAgentIds: vi.fn(),
      setChatInput: vi.fn(),
      setOrchestration: vi.fn(),
    })))

    expect(fetchDesktopAttachment).not.toHaveBeenCalled()

    await act(async () => mounted.render(createElement(AssistantChatCard, {
      addable: [],
      addAgentIds: [],
      assistant: { id: 'x', name: '助理' },
      chatBoxRef: { current: null },
      chatInput: '',
      chatMessages: [imageMessage('2026-07-24T08:00:00Z')],
      chatSending: false,
      chatUploading: false,
      pendingAttachments: [],
      replyingTo: null,
      orchestration: null,
      onAcceptStep: vi.fn(),
      onCancelReply: vi.fn(),
      onDownloadAttachment: vi.fn(),
      onPinToggle: vi.fn(),
      onRemoveAttachment: vi.fn(),
      onReply: vi.fn(),
      onSend: vi.fn(),
      onUpload: vi.fn(),
      setAddAgentIds: vi.fn(),
      setChatInput: vi.fn(),
      setOrchestration: vi.fn(),
    })))

    expect(fetchDesktopAttachment).toHaveBeenCalledTimes(1)

    await act(async () => mounted.unmount())
    fetchDesktopAttachment.mockRestore()
    host.remove()
  })
})

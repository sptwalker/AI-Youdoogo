import { describe, expect, it } from 'vitest'
import type { DesktopMessage } from '../api/desktop'
import {
  mergeDesktopChatMessages,
  reconcileDesktopMessageEnd,
  startDesktopStreamingMessage,
} from '../components/dashboard/desktopChatModel'

function message(overrides: Partial<DesktopMessage> = {}): DesktopMessage {
  return {
    id: 'm-1',
    speaker_type: 'ai',
    speaker_agent_id: 'agent-1',
    speaker_name: '助理',
    content: 'hello',
    create_time: '2026-07-24T08:00:00Z',
    reply_to_message_id: null,
    reply_preview: null,
    attachments: [],
    is_pinned: false,
    pinned_at: null,
    pinned_by_user_id: null,
    ...overrides,
  }
}

describe('Dashboard desktop chat reconciliation helpers', () => {
  it('replaces optimistic user message with persisted message', () => {
    const optimistic = message({
      id: 'tmp-1',
      speaker_type: 'user',
      speaker_agent_id: null,
      speaker_name: '我',
      content: '待发送',
      create_time: '',
    })
    const persisted = message({
      id: 'db-user-1',
      speaker_type: 'user',
      speaker_agent_id: null,
      speaker_name: '爱丽丝',
      content: '已落库',
    })

    const items = reconcileDesktopMessageEnd([optimistic], persisted, optimistic.id)

    expect(items).toEqual([persisted])
  })

  it('removes streaming placeholder and appends persisted ai message', () => {
    const existing = message({ id: 'existing', speaker_name: '我', speaker_type: 'user' })
    const streaming = message({
      id: '__streaming__',
      content: '流式中',
      create_time: '',
    })
    const persisted = message({ id: 'db-ai-1', content: '最终回复' })

    const items = reconcileDesktopMessageEnd([existing, streaming], persisted, 'tmp-1')

    expect(items).toEqual([existing, persisted])
  })

  it('deduplicates duplicate persisted ai message on message_end', () => {
    const persisted = message({ id: 'db-ai-1', content: '最终回复' })
    const items = reconcileDesktopMessageEnd(
      [message({ id: '__streaming__', content: '流式中', create_time: '' }), persisted],
      persisted,
      'tmp-1',
    )

    expect(items).toEqual([persisted])
  })

  it('restarts streaming placeholder from a clean single row', () => {
    const oldStreaming = message({
      id: '__streaming__',
      speaker_name: '旧助理',
      content: '旧流',
      create_time: '',
    })
    const existing = message({ id: 'existing', speaker_type: 'user', speaker_agent_id: null, speaker_name: '我' })

    const items = startDesktopStreamingMessage([existing, oldStreaming], {
      speaker_agent_id: 'agent-2',
      speaker_name: '新助理',
    })

    expect(items).toEqual([
      existing,
      {
        id: '__streaming__',
        speaker_type: 'ai',
        speaker_agent_id: 'agent-2',
        speaker_name: '新助理',
        content: '',
        create_time: '',
        reply_to_message_id: null,
        reply_preview: null,
        attachments: [],
        is_pinned: false,
        pinned_at: null,
        pinned_by_user_id: null,
      },
    ])
  })

  it('keeps optimistic and streaming rows when initial fetch resolves late', () => {
    const fetched = [message({ id: 'db-old-1', content: '旧历史' })]
    const optimistic = message({
      id: 'tmp-1',
      speaker_type: 'user',
      speaker_agent_id: null,
      speaker_name: '我',
      content: '刚发送',
      create_time: '',
    })
    const streaming = message({
      id: '__streaming__',
      speaker_name: '助理',
      content: '流式中',
      create_time: '',
    })

    const items = mergeDesktopChatMessages(fetched, [optimistic, streaming])

    expect(items).toEqual([fetched[0], optimistic, streaming])
  })

  it('preserves locally persisted newer rows when fetched history is stale', () => {
    const fetched = [message({ id: 'db-old-1', content: '旧历史' })]
    const localPersisted = message({ id: 'db-new-1', content: '刚刚落库的新消息' })

    const items = mergeDesktopChatMessages(fetched, [localPersisted])

    expect(items).toEqual([fetched[0], localPersisted])
  })

  it('keeps local persisted copy when late fetch returns the same message id', () => {
    const fetchedPersisted = message({ id: 'db-1', content: '服务端版本' })
    const localPersisted = message({ id: 'db-1', content: '本地旧版本' })

    const items = mergeDesktopChatMessages([fetchedPersisted], [localPersisted])

    expect(items).toEqual([localPersisted])
  })
})

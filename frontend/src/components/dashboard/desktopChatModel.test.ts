import { describe, expect, it } from 'vitest'
import type { DesktopMessage } from '../../api/desktop'
import {
  appendDesktopAiDelta,
  beginDesktopAiTurn,
  reconcileDesktopStreamMessageEnd,
} from './desktopChatModel'

function persisted(id: string, speakerType: 'user' | 'ai', content: string): DesktopMessage {
  return {
    id,
    speaker_type: speakerType,
    speaker_agent_id: speakerType === 'ai' ? `agent-${id}` : null,
    speaker_name: speakerType === 'ai' ? 'AI' : '我',
    content,
    create_time: '2026-07-24T00:00:00Z',
    reply_to_message_id: null,
    reply_preview: null,
    attachments: [],
    is_pinned: false,
    pinned_at: null,
    pinned_by_user_id: null,
  }
}

describe('desktop chat stream model', () => {
  it('keeps sequential AI turns isolated and replaces only the current turn', () => {
    let messages: DesktopMessage[] = []
    messages = beginDesktopAiTurn(messages, null, '__streaming__-1', {
      speaker_agent_id: 'agent-1', speaker_name: 'Planner',
    })
    messages = appendDesktopAiDelta(messages, '__streaming__-1', 'first draft')
    messages = reconcileDesktopStreamMessageEnd(
      messages, persisted('ai-1', 'ai', 'first answer'), 'optimistic-user', '__streaming__-1',
    )
    messages = beginDesktopAiTurn(messages, null, '__streaming__-2', {
      speaker_agent_id: 'agent-2', speaker_name: 'Reviewer',
    })
    messages = appendDesktopAiDelta(messages, '__streaming__-2', 'second draft')
    messages = reconcileDesktopStreamMessageEnd(
      messages, persisted('ai-2', 'ai', 'second answer'), 'optimistic-user', '__streaming__-2',
    )

    expect(messages.map((item) => [item.id, item.content])).toEqual([
      ['ai-1', 'first answer'],
      ['ai-2', 'second answer'],
    ])
  })

  it('appends a direct AI message_end and discards a stale consecutive start', () => {
    let messages = reconcileDesktopStreamMessageEnd(
      [], persisted('orchestration-message', 'ai', '任务已开始'), 'optimistic-user', null,
    )
    messages = beginDesktopAiTurn(messages, null, '__streaming__-1', {
      speaker_agent_id: 'agent-1', speaker_name: 'Planner',
    })
    messages = appendDesktopAiDelta(messages, '__streaming__-1', 'stale')
    messages = beginDesktopAiTurn(messages, '__streaming__-1', '__streaming__-2', {
      speaker_agent_id: 'agent-2', speaker_name: 'Reviewer',
    })
    messages = appendDesktopAiDelta(messages, '__streaming__-2', 'current')

    expect(messages.map((item) => [item.id, item.content])).toEqual([
      ['orchestration-message', '任务已开始'],
      ['__streaming__-2', 'current'],
    ])
  })
})

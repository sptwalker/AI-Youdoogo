import { describe, expect, it } from 'vitest'
import type { Attachment, DiscussionMember, Message } from './api'
import {
  MAX_ATTACHMENT_BYTES,
  STREAMING_MESSAGE_ID,
  buildOutgoingMessage,
  buildMembersToAdd,
  canRemoveMember,
  isAttachmentTooLarge,
  messageSessionReducer,
  type MessageSessionState,
} from './model'

function attachment(name = 'brief.pdf'): Attachment {
  return { type: 'file', name, storage_path: `chat/${name}`, size: 128 }
}

function chatMessage(id: string, channelId = 'channel-a', content = id): Message {
  return {
    id,
    channel_id: channelId,
    speaker_type: 'human',
    speaker_id: 'human-1',
    speaker_name: 'Zoey',
    content,
    mentioned_agent_ids: [],
    ai_source_record_id: null,
    ref_type: null,
    ref_id: null,
    create_time: '2026-07-23T00:00:00Z',
  }
}

describe('message session state', () => {
  it('merges a refresh in server order, deduplicates ids, and retains just-arrived current-channel messages', () => {
    const state = {
      channelId: 'channel-a',
      messages: [
        chatMessage('server-2'),
        chatMessage('realtime-only'),
        chatMessage('other-channel', 'channel-b'),
      ],
    }

    const next = messageSessionReducer(state, {
      type: 'refresh_succeeded',
      channelId: 'channel-a',
      messages: [chatMessage('server-1'), chatMessage('server-2')],
    })

    expect(next.messages.map((item) => item.id)).toEqual([
      'server-1',
      'server-2',
      'realtime-only',
    ])
  })

  it('ignores stale-channel refreshes and realtime events and deduplicates repeated realtime delivery', () => {
    const state = { channelId: 'channel-b', messages: [chatMessage('existing', 'channel-b')] }

    expect(messageSessionReducer(state, {
      type: 'refresh_succeeded',
      channelId: 'channel-a',
      messages: [chatMessage('stale')],
    })).toBe(state)
    expect(messageSessionReducer(state, {
      type: 'realtime_received',
      message: chatMessage('wrong-channel'),
    })).toBe(state)

    const added = messageSessionReducer(state, {
      type: 'realtime_received',
      message: chatMessage('live', 'channel-b'),
    })
    expect(added.messages.map((item) => item.id)).toEqual(['existing', 'live'])
    expect(messageSessionReducer(added, {
      type: 'realtime_received',
      message: chatMessage('live', 'channel-b'),
    })).toBe(added)
  })

  it('preserves message_start, ordered deltas, and message_end reconciliation', () => {
    let state: MessageSessionState = {
      channelId: 'channel-a',
      messages: [chatMessage('human-message')],
    }
    state = messageSessionReducer(state, {
      type: 'stream_started',
      channelId: 'channel-a',
      speakerAgentId: 'agent-1',
      speakerName: 'Advisor',
    })
    state = messageSessionReducer(state, {
      type: 'stream_delta', channelId: 'channel-a', text: 'first ',
    })
    state = messageSessionReducer(state, {
      type: 'stream_delta', channelId: 'channel-a', text: 'second',
    })

    expect(state.messages.at(-1)).toMatchObject({
      id: STREAMING_MESSAGE_ID,
      speaker_name: 'Advisor',
      content: 'first second',
    })

    const persisted = { ...chatMessage('ai-final', 'channel-a', 'first second'), speaker_type: 'ai' as const }
    state = messageSessionReducer(state, { type: 'stream_ended', message: persisted })
    expect(state.messages.map((item) => item.id)).toEqual(['human-message', 'ai-final'])

    const deliveredFirst = {
      channelId: 'channel-a',
      messages: [persisted, { ...persisted, id: STREAMING_MESSAGE_ID }],
    }
    expect(messageSessionReducer(deliveredFirst, {
      type: 'stream_ended',
      message: persisted,
    }).messages.map((item) => item.id)).toEqual(['ai-final'])

    const failed = messageSessionReducer({
      channelId: 'channel-a',
      messages: [chatMessage('human-message'), { ...persisted, id: STREAMING_MESSAGE_ID }],
    }, { type: 'stream_failed', channelId: 'channel-a' })
    expect(failed.messages.map((item) => item.id)).toEqual(['human-message'])
  })
})

describe('message composition', () => {
  const members: DiscussionMember[] = [
    { member_type: 'human', member_id: 'human-1', member_name: 'Alice' },
    { member_type: 'ai', member_id: 'ai-1', member_name: 'Planner' },
    { member_type: 'ai', member_id: 'ai-2', member_name: 'Reviewer' },
    { member_type: 'ai', member_id: 'ai-3', member_name: 'Writer' },
    { member_type: 'ai', member_id: 'ai-4', member_name: 'Observer' },
  ]

  it('prefixes selected names and limits AI responders to three without hiding mentions', () => {
    const outgoing = buildOutgoingMessage({
      members,
      mentionIds: members.map((member) => member.member_id),
      text: '  please review  ',
      attachments: [],
    })

    expect(outgoing).toEqual({
      content: '@Alice @Planner @Reviewer @Writer @Observer please review',
      mentionedAgentIds: ['ai-1', 'ai-2', 'ai-3'],
      attachments: [],
    })
  })

  it('uses the existing attachment placeholder and rejects an empty submission', () => {
    expect(buildOutgoingMessage({
      members,
      mentionIds: [],
      text: '',
      attachments: [attachment()],
    })).toMatchObject({ content: '[附件]' })
    expect(buildOutgoingMessage({
      members,
      mentionIds: [],
      text: '   ',
      attachments: [],
    })).toBeNull()
  })

  it('keeps the 20 MB attachment boundary inclusive', () => {
    expect(isAttachmentTooLarge(MAX_ATTACHMENT_BYTES)).toBe(false)
    expect(isAttachmentTooLarge(MAX_ATTACHMENT_BYTES + 1)).toBe(true)
  })
})

describe('membership policy', () => {
  const owner: DiscussionMember = {
    member_type: 'human', member_id: 'owner-1', member_name: 'Owner',
  }
  const colleague: DiscussionMember = {
    member_type: 'human', member_id: 'human-2', member_name: 'Colleague',
  }

  it('never offers owner removal and only offers other removal actions to the owner', () => {
    expect(canRemoveMember(owner, true, 'owner-1')).toBe(false)
    expect(canRemoveMember(colleague, false, 'owner-1')).toBe(false)
    expect(canRemoveMember(colleague, true, 'owner-1')).toBe(true)
  })

  it('maps selected human and AI identities to the existing mutation payload', () => {
    expect(buildMembersToAdd(
      ['human-2'],
      ['ai-1'],
      [{
        id: 'human-2', real_name: 'Alice', username: 'alice', en_name: '', title: '', department_id: null,
      }],
      [{
        id: 'ai-1', name: 'Planner', duty: null, model_role: 'planner', permission_scope: {}, tools: [], is_active: true,
      }],
    )).toEqual([
      { member_type: 'human', member_id: 'human-2', member_name: 'Alice' },
      { member_type: 'ai', member_id: 'ai-1', member_name: 'Planner' },
    ])
  })
})

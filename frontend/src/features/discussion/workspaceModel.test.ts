import { describe, expect, it } from 'vitest'
import type { AgentRole, Colleague } from './api'
import {
  buildCreateDiscussionRequest,
  channelSignature,
  incrementUnreadForIncoming,
  reconcileActiveConversation,
} from './workspaceModel'

const channels = [
  {
    id: 'channel-a', name: 'A', department_id: null, default_agent_id: null,
    creator_id: 'owner-1', is_archived: false, create_time: '', unread: 1,
  },
  {
    id: 'channel-b', name: 'B', department_id: null, default_agent_id: null,
    creator_id: 'owner-2', is_archived: false, create_time: '', unread: 2,
  },
]

describe('discussion workspace model', () => {
  it('increments unread only for a non-active channel and keeps unknown channels unchanged', () => {
    expect(incrementUnreadForIncoming(channels, 'channel-b', 'channel-a'))
      .toMatchObject([{ unread: 1 }, { unread: 3 }])
    expect(incrementUnreadForIncoming(channels, 'channel-a', 'channel-a')).toBe(channels)
    expect(incrementUnreadForIncoming(channels, 'missing', 'channel-a')).toBe(channels)
  })

  it('uses an order-independent signature and falls back when the active group disappears', () => {
    expect(channelSignature(channels)).toBe('channel-a,channel-b')
    expect(channelSignature([...channels].reverse())).toBe('channel-a,channel-b')
    expect(reconcileActiveConversation(
      { type: 'group', id: 'channel-a', name: 'A' },
      channels.slice(1),
    )).toEqual({ type: 'assistant' })
    expect(reconcileActiveConversation(
      { type: 'group', id: 'channel-b', name: 'B' },
      channels,
    )).toEqual({ type: 'group', id: 'channel-b', name: 'B' })
  })

  it('trims the group name and maps selected human and AI identities', () => {
    const colleagues: Colleague[] = [{
      id: 'human-1', real_name: 'Alice', username: 'alice', en_name: '', title: '', department_id: null,
    }]
    const agents: AgentRole[] = [{
      id: 'ai-1', name: 'Planner', duty: null, model_role: 'planner',
      permission_scope: {}, tools: [], is_active: true,
    }]

    expect(buildCreateDiscussionRequest({
      name: '  Launch room  ',
      humanIds: ['human-1'],
      agentIds: ['ai-1'],
      colleagues,
      agents,
    })).toEqual({
      name: 'Launch room',
      members: [
        { member_type: 'human', member_id: 'human-1', member_name: 'Alice' },
        { member_type: 'ai', member_id: 'ai-1', member_name: 'Planner' },
      ],
    })
    expect(buildCreateDiscussionRequest({
      name: '   ', humanIds: [], agentIds: [], colleagues, agents,
    })).toBeNull()
  })
})

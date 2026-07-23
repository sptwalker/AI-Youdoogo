import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import type { Message } from '../api'
import { ChannelActions } from './ChannelActions'
import { MessageList } from './MessageList'

function message(id: string, speakerType: 'human' | 'ai', content: string): Message {
  return {
    id,
    channel_id: 'channel-a',
    speaker_type: speakerType,
    speaker_id: `${speakerType}-1`,
    speaker_name: speakerType === 'ai' ? 'Planner' : 'Alice',
    content,
    mentioned_agent_ids: [],
    ai_source_record_id: null,
    ref_type: null,
    ref_id: null,
    create_time: '2026-07-23T00:00:00Z',
  }
}

describe('discussion presentation', () => {
  it('preserves message order, AI Markdown, attachment previews, and sending feedback', () => {
    const human = {
      ...message('human-message', 'human', 'human plain text'),
      attachments: [{
        type: 'file' as const,
        name: 'brief plan.pdf',
        storage_path: 'chat/brief plan.pdf',
        size: 128,
      }],
    }
    const ai = {
      ...message('ai-message', 'ai', '**AI markdown**'),
      attachments: [{
        type: 'image' as const,
        name: 'diagram.png',
        storage_path: 'chat/diagram.png',
        size: 256,
      }],
    }

    const markup = renderToStaticMarkup(
      <MessageList messages={[human, ai]} sending onDownload={vi.fn()} />,
    )

    expect(markup.indexOf('human plain text')).toBeLessThan(markup.indexOf('AI markdown'))
    expect(markup).toContain('<strong>AI markdown</strong>')
    expect(markup).toContain('brief plan.pdf')
    expect(markup).toContain('storage_path=chat%2Fdiagram.png')
    expect(markup).toContain('ant-spin')
  })

  it('preserves the empty state and owner-only channel actions', () => {
    const emptyMarkup = renderToStaticMarkup(
      <MessageList messages={[]} sending={false} onDownload={vi.fn()} />,
    )
    expect(emptyMarkup).toContain('群里还没有消息')

    const ownerMarkup = renderToStaticMarkup(
      <ChannelActions
        channelName="Design Group"
        memberCount={4}
        isOwner
        onOpenMembers={vi.fn()}
        onOpenPicker={vi.fn()}
        onDisband={vi.fn().mockResolvedValue(undefined)}
      />,
    )
    expect(ownerMarkup).toContain('Design Group')
    expect(ownerMarkup).toContain('4 成员')
    expect(ownerMarkup).toContain('群主')
    expect(ownerMarkup).toContain('解散群')
  })
})

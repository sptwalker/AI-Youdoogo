import type { DesktopMessage } from '../../api/desktop'

export const DESKTOP_STREAMING_MESSAGE_PREFIX = '__streaming__-'
const LEGACY_STREAMING_MESSAGE_ID = '__streaming__'
const MAX_REPLY_PREVIEW_CHARS = 120

function upsertDesktopMessage(items: DesktopMessage[], persisted: DesktopMessage): DesktopMessage[] {
  const persistedIndex = items.findIndex((item) => item.id === persisted.id)
  if (persistedIndex < 0) return [...items, persisted]
  return items.map((item, index) => (index === persistedIndex ? persisted : item))
}

export function startDesktopStreamingMessage(
  items: DesktopMessage[],
  start: { speaker_agent_id: string | null; speaker_name: string },
): DesktopMessage[] {
  return [
    ...items.filter((item) => item.id !== LEGACY_STREAMING_MESSAGE_ID),
    {
      id: LEGACY_STREAMING_MESSAGE_ID,
      speaker_type: 'ai',
      speaker_agent_id: start.speaker_agent_id,
      speaker_name: start.speaker_name,
      content: '',
      create_time: '',
      reply_to_message_id: null,
      reply_preview: null,
      attachments: [],
      is_pinned: false,
      pinned_at: null,
      pinned_by_user_id: null,
    },
  ]
}

export function reconcileDesktopMessageEnd(
  items: DesktopMessage[],
  persisted: DesktopMessage,
  optimisticId: string,
): DesktopMessage[] {
  const placeholderId = persisted.speaker_type === 'user' ? optimisticId : LEGACY_STREAMING_MESSAGE_ID
  const withoutPlaceholder = items.filter((item) => item.id !== placeholderId)
  return upsertDesktopMessage(withoutPlaceholder, persisted)
}

export function buildReplyPreview(messageRow: DesktopMessage): DesktopMessage['reply_preview'] {
  const compact = messageRow.content.split(/\s+/).filter(Boolean).join(' ')
  return {
    id: messageRow.id,
    speaker_name: messageRow.speaker_name,
    content: compact.length <= MAX_REPLY_PREVIEW_CHARS
      ? compact
      : `${compact.slice(0, MAX_REPLY_PREVIEW_CHARS - 1)}…`,
  }
}

export function mergeDesktopChatMessages(
  fetched: DesktopMessage[],
  current: DesktopMessage[],
): DesktopMessage[] {
  if (current.length === 0) return fetched
  let merged = [...fetched]
  for (const item of current) {
    if (item.id === LEGACY_STREAMING_MESSAGE_ID || item.id.startsWith('tmp-')) {
      if (!merged.some((message) => message.id === item.id)) merged = [...merged, item]
      continue
    }
    merged = upsertDesktopMessage(merged, item)
  }
  return merged
}

export function beginDesktopAiTurn(
  messages: DesktopMessage[],
  previousTurnId: string | null,
  turnId: string,
  speaker: { speaker_agent_id: string | null; speaker_name: string },
): DesktopMessage[] {
  const withoutStaleTurn = previousTurnId
    ? messages.filter((item) => item.id !== previousTurnId)
    : messages
  return [...withoutStaleTurn, {
    id: turnId,
    speaker_type: 'ai',
    speaker_agent_id: speaker.speaker_agent_id,
    speaker_name: speaker.speaker_name,
    content: '',
    create_time: '',
    reply_to_message_id: null,
    reply_preview: null,
    attachments: [],
    is_pinned: false,
    pinned_at: null,
    pinned_by_user_id: null,
  }]
}

export function appendDesktopAiDelta(
  messages: DesktopMessage[],
  activeTurnId: string | null,
  text: string,
): DesktopMessage[] {
  if (!activeTurnId) return messages
  return messages.map((item) => (
    item.id === activeTurnId ? { ...item, content: item.content + text } : item
  ))
}

export function reconcileDesktopStreamMessageEnd(
  messages: DesktopMessage[],
  persisted: DesktopMessage,
  optimisticUserId: string,
  activeAiTurnId: string | null,
): DesktopMessage[] {
  const replacementId = persisted.speaker_type === 'user'
    ? optimisticUserId
    : activeAiTurnId
  const replacementExists = replacementId !== null
    && messages.some((item) => item.id === replacementId)

  if (replacementExists) {
    return messages.map((item) => item.id === replacementId ? persisted : item)
  }
  if (messages.some((item) => item.id === persisted.id)) return messages
  return [...messages, persisted]
}

export function clearFailedDesktopChat(
  messages: DesktopMessage[],
  optimisticUserId: string,
): DesktopMessage[] {
  return messages.filter((item) => (
    item.id !== optimisticUserId
    && !item.id.startsWith(DESKTOP_STREAMING_MESSAGE_PREFIX)
  ))
}

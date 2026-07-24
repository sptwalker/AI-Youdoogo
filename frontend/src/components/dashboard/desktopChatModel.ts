import type { DesktopMessage } from '../../api/desktop'

export const DESKTOP_STREAMING_MESSAGE_PREFIX = '__streaming__-'

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

export function reconcileDesktopMessageEnd(
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

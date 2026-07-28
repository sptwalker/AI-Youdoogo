import type { DesktopMessage } from '../../api/desktop'

const TIME_SEPARATOR_GAP_MS = 3 * 60 * 1000

export function parseMessageTime(createTime: string): Date | null {
  if (!createTime) return null
  const parsed = new Date(createTime)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

export function shouldShowTimeSeparator(
  previousCreateTime: string | null | undefined,
  currentCreateTime: string,
): boolean {
  const currentTime = parseMessageTime(currentCreateTime)
  if (!currentTime) return false
  if (previousCreateTime == null) return true
  if (!previousCreateTime) return false
  const previousTime = parseMessageTime(previousCreateTime)
  if (!previousTime) return false
  return currentTime.getTime() - previousTime.getTime() > TIME_SEPARATOR_GAP_MS
}

export function sortPinnedMessages(messages: DesktopMessage[]): DesktopMessage[] {
  return messages
    .filter((message) => message.is_pinned)
    .sort((left, right) => (right.pinned_at ?? '').localeCompare(left.pinned_at ?? ''))
}

export function formatSeparatorTime(messageTime: Date): string {
  return messageTime.toLocaleString([], {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatExactTimestamp(messageTime: Date): string {
  return messageTime.toLocaleString()
}

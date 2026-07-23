import { useCallback, useRef, useState } from 'react'
import { groupChatApi, type GroupChatApi } from '../api'

interface UseAdvisorComposerOptions {
  channelId: string
  ingestStreamEvent(event: string, data: Record<string, unknown>): void
  clearStreamingMessage(): void
  api?: GroupChatApi
}

export interface AdvisorComposerState {
  text: string
  mentions: string[]
  sending: boolean
  setText(value: string): void
  setMentions(value: string[]): void
  send(): Promise<void>
}

export function useAdvisorComposer({
  channelId,
  ingestStreamEvent,
  clearStreamingMessage,
  api = groupChatApi,
}: UseAdvisorComposerOptions): AdvisorComposerState {
  const [text, setText] = useState('')
  const [mentions, setMentions] = useState<string[]>([])
  const [sending, setSending] = useState(false)
  const sendingRef = useRef(false)

  const send = useCallback(async () => {
    const content = text.trim()
    if (!content || sendingRef.current) return
    sendingRef.current = true
    setSending(true)
    try {
      await api.postMessage(
        channelId,
        content,
        mentions.slice(0, 3),
        ingestStreamEvent,
      )
      setText('')
      setMentions([])
    } catch {
      clearStreamingMessage()
    } finally {
      sendingRef.current = false
      setSending(false)
    }
  }, [api, channelId, clearStreamingMessage, ingestStreamEvent, mentions, text])

  return { text, mentions, sending, setText, setMentions, send }
}

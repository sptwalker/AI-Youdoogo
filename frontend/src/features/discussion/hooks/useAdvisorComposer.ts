import { useCallback, useState } from 'react'
import { groupChatApi, type GroupChatApi } from '../api'
import { useStreamingSend } from './useStreamingSend'

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
  const { sending, sendingRef, submit } = useStreamingSend(clearStreamingMessage)

  const send = useCallback(async () => {
    const content = text.trim()
    if (!content || sendingRef.current) return
    await submit(async (signal) => {
      await api.postMessage(channelId, content, mentions.slice(0, 3), ingestStreamEvent, [], { signal })
      setText('')
      setMentions([])
    })
  }, [api, channelId, ingestStreamEvent, mentions, sendingRef, submit, text])

  return { text, mentions, sending, setText, setMentions, send }
}

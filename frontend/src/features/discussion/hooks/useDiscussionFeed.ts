import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import {
  discussionWorkspaceApi,
  type ChannelWithUnread,
  type DiscussionWorkspaceApi,
  type Message,
} from '../api'
import {
  POLLING_INTERVAL_MS,
  messageSessionReducer,
  type MessageSessionAction,
} from '../model'
import { channelSignature, incrementUnreadForIncoming } from '../workspaceModel'

const CONNECTED_CHANNEL_POLL_MS = 60000

interface UseDiscussionFeedOptions {
  activeChannelId: string | null
  api?: DiscussionWorkspaceApi
}

export interface ChannelMessageSession {
  messages: Message[]
  ingestStreamEvent(event: string, data: Record<string, unknown>): void
  clearStreamingMessage(): void
  refresh(): void
}

export interface DiscussionFeed {
  channels: ChannelWithUnread[]
  activeSession: ChannelMessageSession
  refreshChannels(forceResubscribe?: boolean): Promise<void>
  restartRealtime(): void
}

/** Owns channel discovery, realtime delivery, fallback polling, and read acknowledgement. */
export function useDiscussionFeed({
  activeChannelId,
  api = discussionWorkspaceApi,
}: UseDiscussionFeedOptions): DiscussionFeed {
  const [channels, setChannels] = useState<ChannelWithUnread[]>([])
  const [realtimeConnected, setRealtimeConnected] = useState(false)
  const [messageState, dispatch] = useReducer(messageSessionReducer, {
    channelId: activeChannelId,
    messages: [],
  })
  const [messageRefreshRevision, setMessageRefreshRevision] = useState(0)
  const activeChannelIdRef = useRef(activeChannelId)
  const channelSignatureRef = useRef<string | null>(null)
  const subscriptionRef = useRef<ReturnType<DiscussionWorkspaceApi['subscribeRealtime']> | null>(null)
  activeChannelIdRef.current = activeChannelId

  useEffect(() => {
    dispatch({ type: 'channel_changed', channelId: activeChannelId })
  }, [activeChannelId])

  const loadChannels = useCallback(async (
    signal?: AbortSignal,
    forceResubscribe = false,
  ) => {
    const items = await api.listChannels({ signal, silent: true })
    if (signal?.aborted) return
    const nextSignature = channelSignature(items)
    const previousSignature = channelSignatureRef.current
    channelSignatureRef.current = nextSignature
    setChannels(items)
    if (
      forceResubscribe
      || (previousSignature !== null && previousSignature !== nextSignature)
    ) {
      subscriptionRef.current?.restart()
    }
  }, [api])

  const markChannelRead = useCallback(async (channelId: string, signal?: AbortSignal) => {
    await api.markRead(channelId, { signal, silent: true })
    if (signal?.aborted) return
    setChannels((current) => current.map((channel) => (
      channel.id === channelId ? { ...channel, unread: 0 } : channel
    )))
  }, [api])

  useEffect(() => {
    const readControllers = new Set<AbortController>()
    const subscription = api.subscribeRealtime((event, data) => {
      if (event !== 'message') return
      const incoming = data as unknown as Message
      const incomingChannelId = incoming.channel_id
      if (!incomingChannelId) return

      setChannels((current) => incrementUnreadForIncoming(
        current,
        incomingChannelId,
        activeChannelIdRef.current,
      ))
      if (incomingChannelId !== activeChannelIdRef.current) return

      dispatch({ type: 'realtime_received', message: incoming })
      const controller = new AbortController()
      readControllers.add(controller)
      void markChannelRead(incomingChannelId, controller.signal)
        .catch(() => {})
        .finally(() => { readControllers.delete(controller) })
    }, (state) => {
      setRealtimeConnected(state === 'connected')
    })
    subscriptionRef.current = subscription
    return () => {
      for (const controller of readControllers) controller.abort()
      if (subscriptionRef.current === subscription) subscriptionRef.current = null
      subscription()
    }
  }, [api, markChannelRead])

  useEffect(() => {
    const controller = new AbortController()
    const intervalMs = realtimeConnected ? CONNECTED_CHANNEL_POLL_MS : POLLING_INTERVAL_MS
    let timer: number | undefined
    let disposed = false

    const poll = async () => {
      try {
        await loadChannels(controller.signal)
      } catch {
        // Channel discovery is a silent fallback and retries on the next interval.
      }
      if (!disposed) timer = window.setTimeout(() => { void poll() }, intervalMs)
    }

    void poll()
    return () => {
      disposed = true
      controller.abort()
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [loadChannels, realtimeConnected])

  useEffect(() => {
    if (!activeChannelId) return
    const controller = new AbortController()
    let timer: number | undefined
    let disposed = false

    const refresh = async () => {
      try {
        const messages = await api.listMessages(activeChannelId, {
          signal: controller.signal,
          silent: true,
        })
        if (disposed || controller.signal.aborted) return
        dispatch({ type: 'refresh_succeeded', channelId: activeChannelId, messages })
        await markChannelRead(activeChannelId, controller.signal)
      } catch {
        // Message polling is a silent fallback and retries while realtime is unavailable.
      }

      if (!disposed && !realtimeConnected) {
        timer = window.setTimeout(() => { void refresh() }, POLLING_INTERVAL_MS)
      }
    }

    void refresh()
    return () => {
      disposed = true
      controller.abort()
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [activeChannelId, api, markChannelRead, messageRefreshRevision, realtimeConnected])

  const ingestStreamEvent = useCallback((event: string, data: Record<string, unknown>) => {
    if (!activeChannelId) return
    let action: MessageSessionAction | null = null
    if (event === 'message_start') {
      action = {
        type: 'stream_started',
        channelId: activeChannelId,
        speakerAgentId: typeof data.speaker_agent_id === 'string' ? data.speaker_agent_id : null,
        speakerName: String(data.speaker_name ?? ''),
      }
    } else if (event === 'delta') {
      action = { type: 'stream_delta', channelId: activeChannelId, text: String(data.text ?? '') }
    } else if (event === 'message_end') {
      action = { type: 'stream_ended', message: data as unknown as Message }
    }
    if (action) dispatch(action)
  }, [activeChannelId])

  const clearStreamingMessage = useCallback(() => {
    if (activeChannelId) dispatch({ type: 'stream_failed', channelId: activeChannelId })
  }, [activeChannelId])

  const refreshMessages = useCallback(() => {
    setMessageRefreshRevision((revision) => revision + 1)
  }, [])

  const refreshChannels = useCallback(async (forceResubscribe = false) => {
    await loadChannels(undefined, forceResubscribe)
  }, [loadChannels])

  const restartRealtime = useCallback(() => {
    subscriptionRef.current?.restart()
  }, [])

  return {
    channels,
    activeSession: {
      messages: messageState.channelId === activeChannelId ? messageState.messages : [],
      ingestStreamEvent,
      clearStreamingMessage,
      refresh: refreshMessages,
    },
    refreshChannels,
    restartRealtime,
  }
}

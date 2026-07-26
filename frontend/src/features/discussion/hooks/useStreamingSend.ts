import { useCallback, useEffect, useRef, useState } from 'react'

export interface StreamingSend {
  sending: boolean
  /** True while a send is in flight; read it in a composer's own gate before calling submit. */
  sendingRef: { readonly current: boolean }
  /**
   * Own the one shared send lifecycle: single-flight guard, AbortController, sending flag,
   * and stream cleanup on failure. `perform` does the transport call plus any on-success
   * draft reset — a throw skips those, preserving the draft, exactly as both composers need.
   */
  submit(perform: (signal: AbortSignal) => Promise<void>): Promise<void>
}

export function useStreamingSend(onStreamError: () => void): StreamingSend {
  const [sending, setSending] = useState(false)
  const sendingRef = useRef(false)
  const activeRequestRef = useRef<AbortController | null>(null)

  useEffect(() => () => activeRequestRef.current?.abort(), [])

  const submit = useCallback(async (perform: (signal: AbortSignal) => Promise<void>) => {
    const controller = new AbortController()
    activeRequestRef.current = controller
    sendingRef.current = true
    setSending(true)
    try {
      await perform(controller.signal)
    } catch {
      onStreamError()
    } finally {
      if (activeRequestRef.current === controller) activeRequestRef.current = null
      sendingRef.current = false
      setSending(false)
    }
  }, [onStreamError])

  return { sending, sendingRef, submit }
}

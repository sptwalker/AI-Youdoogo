import { useCallback, useEffect, useRef, useState } from 'react'

export function usePendingActions() {
  const [pendingKeys, setPendingKeys] = useState<ReadonlySet<string>>(() => new Set())
  const pendingRef = useRef(new Set<string>())
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const run = useCallback(async <T,>(key: string, action: () => Promise<T>): Promise<T | undefined> => {
    if (pendingRef.current.has(key)) return undefined
    pendingRef.current.add(key)
    setPendingKeys(new Set(pendingRef.current))
    try {
      return await action()
    } finally {
      pendingRef.current.delete(key)
      if (mountedRef.current) setPendingKeys(new Set(pendingRef.current))
    }
  }, [])

  const isPending = useCallback((key: string) => pendingKeys.has(key), [pendingKeys])

  return { isPending, run }
}

import { useCallback, useEffect, useRef, useState } from 'react'
import { listUsers, type UserInfo } from '../api/auth'
import { getDesktop, listDeliverables, type Deliverable, type Desktop } from '../api/desktop'

export function useDashboardData(me: UserInfo | null) {
  const [data, setData] = useState<Desktop | null>(null)
  const [viewUser, setViewUser] = useState<string | undefined>()
  const [users, setUsers] = useState<UserInfo[]>([])
  const [deliverables, setDeliverables] = useState<Deliverable[]>([])
  const desktopRequestRef = useRef(0)
  const deliverablesRequestRef = useRef(0)

  const reload = useCallback(async () => {
    const requestId = ++desktopRequestRef.current
    const next = await getDesktop(viewUser)
    if (requestId === desktopRequestRef.current) setData(next)
  }, [viewUser])
  const loadDeliverables = useCallback(async () => {
    const requestId = ++deliverablesRequestRef.current
    const next = await listDeliverables(viewUser)
    if (requestId === deliverablesRequestRef.current) setDeliverables(next)
  }, [viewUser])

  useEffect(() => {
    setData(null)
    void reload().catch(() => {})
    return () => { desktopRequestRef.current += 1 }
  }, [reload])

  useEffect(() => {
    setDeliverables([])
    void loadDeliverables().catch(() => {})
    return () => { deliverablesRequestRef.current += 1 }
  }, [loadDeliverables])

  useEffect(() => {
    let disposed = false
    if (me?.role_code === 'admin') {
      void listUsers()
        .then((items) => { if (!disposed) setUsers(items) })
        .catch(() => {})
    } else {
      setUsers([])
    }
    return () => { disposed = true }
  }, [me])

  return {
    data,
    deliverables,
    loadDeliverables,
    reload,
    setViewUser,
    users,
    viewUser,
  }
}

import { useCallback, useEffect, useState } from 'react'
import { listUsers, type UserInfo } from '../api/auth'
import { getDesktop, listDeliverables, type Deliverable, type Desktop } from '../api/desktop'

export function useDashboardData(me: UserInfo | null) {
  const [data, setData] = useState<Desktop | null>(null)
  const [viewUser, setViewUser] = useState<string | undefined>()
  const [users, setUsers] = useState<UserInfo[]>([])
  const [deliverables, setDeliverables] = useState<Deliverable[]>([])

  const reload = useCallback(async () => setData(await getDesktop(viewUser)), [viewUser])
  const loadDeliverables = useCallback(async () => {
    setDeliverables(await listDeliverables(viewUser))
  }, [viewUser])

  useEffect(() => {
    void reload()
  }, [reload])

  useEffect(() => {
    void loadDeliverables()
  }, [loadDeliverables])

  useEffect(() => {
    if (me?.role_code === 'admin') void listUsers().then(setUsers)
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

import { useCallback, useEffect, useRef, useState } from 'react'
import { message } from 'antd'
import { dataSourcesApi, type OpsEventGroup } from '../api'
import { aliasesFromEdits, defaultEventDate, editsFromGroups } from '../model'

export function useEventNaming() {
  const [statDate, setStatDate] = useState(defaultEventDate)
  const [groups, setGroups] = useState<OpsEventGroup[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [edits, setEdits] = useState<Record<string, string>>({})
  const initialDateRef = useRef(statDate)

  const loadForDate = useCallback(async (date: string) => {
    setLoading(true)
    try {
      const items = await dataSourcesApi.listOpsEvents(date)
      setGroups(items)
      setEdits(editsFromGroups(items))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadForDate(initialDateRef.current)
  }, [loadForDate])

  const load = useCallback(async () => {
    await loadForDate(statDate)
  }, [loadForDate, statDate])

  const save = useCallback(async () => {
    setSaving(true)
    try {
      const { saved } = await dataSourcesApi.saveEventAliases(aliasesFromEdits(edits))
      message.success(`已保存 ${saved} 条命名`)
      await loadForDate(statDate)
    } finally {
      setSaving(false)
    }
  }, [edits, loadForDate, statDate])

  const updateEdit = useCallback((key: string, value: string) => {
    setEdits((current) => ({ ...current, [key]: value }))
  }, [])

  return {
    statDate,
    setStatDate,
    groups,
    loading,
    saving,
    edits,
    updateEdit,
    load,
    save,
  }
}

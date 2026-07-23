import { useEffect, useState } from 'react'
import { dataSourcesApi, flattenDepts } from '../api'

export interface SelectOption {
  value: string
  label: string
}

export function useDataSourceOptions() {
  const [departments, setDepartments] = useState<SelectOption[]>([])
  const [agents, setAgents] = useState<SelectOption[]>([])

  useEffect(() => {
    let disposed = false
    void dataSourcesApi.getDepartmentTree()
      .then((tree) => { if (!disposed) setDepartments(flattenDepts(tree)) })
      .catch(() => {})
    void dataSourcesApi.listAgents()
      .then((items) => {
        if (!disposed) setAgents(items.map((agent) => ({ value: agent.id, label: agent.name })))
      })
      .catch(() => {})
    return () => { disposed = true }
  }, [])

  return { departments, agents }
}

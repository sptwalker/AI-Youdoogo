import { listRoles, type AgentRole } from '../../api/agents'
import {
  DS_TYPES,
  createDataSource,
  deleteDataSource,
  listDataSources,
  testDataSource,
  updateDataSource,
  type DataSource,
  type DataSourceTestResult,
} from '../../api/dataSources'
import { flattenDepts, getTree, type OrgNode } from '../../api/org'
import {
  listOpsEvents,
  saveEventAliases,
  type OpsEventGroup,
} from '../../api/opsData'

export { DS_TYPES, flattenDepts }
export type { AgentRole, DataSource, DataSourceTestResult, OpsEventGroup, OrgNode }

export interface DataSourcesApi {
  listAgents(): Promise<AgentRole[]>
  getDepartmentTree(): Promise<OrgNode[]>
  listDataSources(): Promise<DataSource[]>
  createDataSource(payload: {
    name: string
    type: string
    code?: string
    department_id?: string
    secret_ref?: string
    owner_agent_id?: string
  }): Promise<{ id: string }>
  updateDataSource: typeof updateDataSource
  deleteDataSource(id: string): Promise<null>
  testDataSource: typeof testDataSource
  listOpsEvents(statDate: string): Promise<OpsEventGroup[]>
  saveEventAliases: typeof saveEventAliases
}

export const dataSourcesApi: DataSourcesApi = {
  listAgents: listRoles,
  getDepartmentTree: getTree,
  listDataSources,
  createDataSource,
  updateDataSource,
  deleteDataSource,
  testDataSource,
  listOpsEvents,
  saveEventAliases,
}

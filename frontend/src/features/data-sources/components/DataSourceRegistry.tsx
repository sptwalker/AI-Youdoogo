import {
  ModalForm,
  ProFormSelect,
  ProFormText,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components'
import { Button, Popconfirm, Tag, message } from 'antd'
import { useRef } from 'react'
import { dataSourcesApi, DS_TYPES, type DataSource } from '../api'
import { secretStatusView } from '../model'
import { useDataSourceOptions } from '../hooks/useDataSourceOptions'

interface DataSourceCreateValues {
  name: string
  code?: string
  type: string
  department_id?: string
  owner_agent_id?: string
  secret_ref?: string
}

export function DataSourceRegistry() {
  const actionRef = useRef<ActionType>(null)
  const { departments, agents } = useDataSourceOptions()
  const reload = () => actionRef.current?.reload()

  const columns: ProColumns<DataSource>[] = [
    { title: '名称', dataIndex: 'name' },
    { title: '编码', dataIndex: 'code', copyable: true },
    { title: '类型', dataIndex: 'type', render: (_, item) => <Tag>{item.type}</Tag> },
    {
      title: '密钥',
      dataIndex: 'secret_status',
      render: (_, item) => {
        const view = secretStatusView(item.secret_status)
        return <Tag color={view.color}>{view.text}</Tag>
      },
    },
    {
      title: '启用',
      dataIndex: 'is_active',
      render: (_, item) => (item.is_active ? '是' : '否'),
    },
    {
      title: '对接AI',
      dataIndex: 'owner_agent_name',
      render: (_, item) => item.owner_agent_name ?? <Tag>未指派</Tag>,
    },
    {
      title: '操作',
      valueType: 'option',
      render: (_, item) => [
        <ModalForm<{
          name: string
          secret_ref?: string
        }>
          key="edit"
          title={`编辑数据接口 · ${item.name}`}
          trigger={<a>编辑</a>}
          modalProps={{ destroyOnHidden: true }}
          initialValues={{ name: item.name, secret_ref: item.secret_ref ?? undefined }}
          onFinish={async (values) => {
            await dataSourcesApi.updateDataSource(item.id, {
              name: values.name,
              secret_ref: values.secret_ref?.trim() ?? '',
            })
            message.success('已保存')
            reload()
            return true
          }}
        >
          <ProFormText name="name" label="名称" rules={[{ required: true }]} />
          <ProFormText
            name="secret_ref"
            label="密钥变量名(.env)"
            tooltip="留空表示该接口不使用密钥；这里只保存变量名，不保存密钥值"
          />
        </ModalForm>,
        <a
          key="active"
          onClick={async () => {
            await dataSourcesApi.updateDataSource(item.id, { is_active: !item.is_active })
            message.success(item.is_active ? '已停用' : '已启用')
            reload()
          }}
        >
          {item.is_active ? '停用' : '启用'}
        </a>,
        <ModalForm
          key="agent"
          title={`指派对接AI · ${item.name}`}
          trigger={<a>对接AI</a>}
          modalProps={{ destroyOnHidden: true }}
          initialValues={{ owner_agent_id: item.owner_agent_id ?? undefined }}
          onFinish={async (values) => {
            await dataSourcesApi.updateDataSource(item.id, {
              owner_agent_id: values.owner_agent_id,
            })
            message.success('已指派对接AI')
            reload()
            return true
          }}
        >
          <ProFormSelect
            name="owner_agent_id"
            label="对接AI"
            options={agents}
            showSearch
            rules={[{ required: true }]}
          />
        </ModalForm>,
        <ModalForm<{ department_id: string }>
          key="department"
          title={`改部门 · ${item.name}`}
          trigger={<a>改部门</a>}
          modalProps={{ destroyOnHidden: true }}
          initialValues={{ department_id: item.department_id }}
          onFinish={async (values) => {
            await dataSourcesApi.updateDataSource(item.id, {
              department_id: values.department_id,
            })
            message.success('已改部门')
            reload()
            return true
          }}
        >
          <ProFormSelect
            name="department_id"
            label="归属部门"
            options={departments}
            rules={[{ required: true }]}
          />
        </ModalForm>,
        <Popconfirm
          key="delete"
          title="删除此数据接口？"
          onConfirm={async () => {
            await dataSourcesApi.deleteDataSource(item.id)
            message.success('已删除')
            reload()
          }}
        >
          <a style={{ color: '#cf1322' }}>删除</a>
        </Popconfirm>,
      ],
    },
  ]

  return (
    <ProTable<DataSource>
      rowKey="id"
      actionRef={actionRef}
      columns={columns}
      search={false}
      options={{ reload: true, density: false, setting: false }}
      request={async () => ({ data: await dataSourcesApi.listDataSources(), success: true })}
      pagination={false}
      toolBarRender={() => [
        <ModalForm<DataSourceCreateValues>
          key="new"
          title="注册数据接口"
          trigger={<Button type="primary">注册数据接口</Button>}
          modalProps={{ destroyOnHidden: true }}
          onFinish={async (values) => {
            await dataSourcesApi.createDataSource({
              ...values,
              code: values.code?.trim() || undefined,
              secret_ref: values.secret_ref?.trim() || undefined,
            })
            message.success('已注册')
            reload()
            return true
          }}
        >
          <ProFormText name="name" label="名称" rules={[{ required: true }]} />
          <ProFormText
            name="code"
            label="编码（可选）"
            tooltip="留空由系统自动生成；对接脚本依赖编码时建议显式填写"
          />
          <ProFormSelect
            name="type"
            label="类型"
            options={DS_TYPES.map((type) => ({ value: type, label: type }))}
            rules={[{ required: true }]}
          />
          <ProFormSelect name="department_id" label="归属部门" options={departments} />
          <ProFormSelect
            name="owner_agent_id"
            label="对接AI"
            options={agents}
            showSearch
            tooltip="负责对接此数据接口的AI员工（进环境快照）"
          />
          <ProFormText
            name="secret_ref"
            label="密钥变量名(.env)"
            tooltip="如 TD_API_SECRET；只存变量名不存值"
          />
        </ModalForm>,
      ]}
    />
  )
}

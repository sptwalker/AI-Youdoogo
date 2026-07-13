/** 数据接口（F5c，仅 admin）：注册/改/删 + 密钥状态 + 改部门。
 *  密钥走 .env（secret_ref 存变量名），此页只显示状态位，不回显值。 */
import {
  ModalForm,
  PageContainer,
  ProFormSelect,
  ProFormText,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components'
import { Button, Popconfirm, Tag, message } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { flattenDepts, getTree } from '../api/org'
import {
  DS_TYPES,
  createDataSource,
  deleteDataSource,
  listDataSources,
  updateDataSource,
  type DataSource,
} from '../api/dataSources'

const SECRET_TAG: Record<DataSource['secret_status'], { color: string; text: string }> = {
  not_set: { color: 'default', text: '无密钥' },
  configured: { color: 'success', text: '已配置' },
  missing: { color: 'error', text: '缺失(.env未设)' },
}

export default function DataSources() {
  const actionRef = useRef<ActionType>(null)
  const [depts, setDepts] = useState<{ value: string; label: string }[]>([])
  useEffect(() => {
    void getTree().then((t) => setDepts(flattenDepts(t)))
  }, [])
  const reload = () => actionRef.current?.reload()

  const columns: ProColumns<DataSource>[] = [
    { title: '名称', dataIndex: 'name' },
    { title: '编码', dataIndex: 'code', copyable: true },
    { title: '类型', dataIndex: 'type', render: (_, r) => <Tag>{r.type}</Tag> },
    {
      title: '密钥', dataIndex: 'secret_status',
      render: (_, r) => <Tag color={SECRET_TAG[r.secret_status].color}>{SECRET_TAG[r.secret_status].text}</Tag>,
    },
    { title: '启用', dataIndex: 'is_active', render: (_, r) => (r.is_active ? '是' : '否') },
    {
      title: '操作', valueType: 'option',
      render: (_, r) => [
        <ModalForm
          key="dept"
          title={`改部门 · ${r.name}`}
          trigger={<a>改部门</a>}
          modalProps={{ destroyOnHidden: true }}
          initialValues={{ department_id: r.department_id }}
          onFinish={async (v) => {
            await updateDataSource(r.id, { department_id: v.department_id })
            message.success('已改部门')
            reload()
            return true
          }}
        >
          <ProFormSelect name="department_id" label="归属部门" options={depts} rules={[{ required: true }]} />
        </ModalForm>,
        <Popconfirm key="del" title="删除此数据接口？" onConfirm={async () => { await deleteDataSource(r.id); message.success('已删除'); reload() }}>
          <a style={{ color: '#cf1322' }}>删除</a>
        </Popconfirm>,
      ],
    },
  ]

  return (
    <PageContainer title="数据接口" subTitle="数据源注册表；密钥走 .env，仅显示状态不回显值">
      <ProTable<DataSource>
        rowKey="id"
        actionRef={actionRef}
        columns={columns}
        search={false}
        options={{ reload: true, density: false, setting: false }}
        request={async () => ({ data: await listDataSources(), success: true })}
        pagination={false}
        toolBarRender={() => [
          <ModalForm
            key="new"
            title="注册数据接口"
            trigger={<Button type="primary">注册数据接口</Button>}
            modalProps={{ destroyOnHidden: true }}
            onFinish={async (v) => {
              await createDataSource(v as { name: string; type: string })
              message.success('已注册')
              reload()
              return true
            }}
          >
            <ProFormText name="name" label="名称" rules={[{ required: true }]} />
            <ProFormSelect name="type" label="类型" options={DS_TYPES.map((t) => ({ value: t, label: t }))} rules={[{ required: true }]} />
            <ProFormSelect name="department_id" label="归属部门" options={depts} />
            <ProFormText name="secret_ref" label="密钥变量名(.env)" tooltip="如 TD_API_SECRET；只存变量名不存值" />
          </ModalForm>,
        ]}
      />
    </PageContainer>
  )
}

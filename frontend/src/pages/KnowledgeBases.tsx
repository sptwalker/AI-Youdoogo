/** 知识库集合（F5c，仅 admin）：建/改/删 + 机密标记 + 改部门 + 授权（resource_grant）。
 *  授权只授内容访问权，不授生效权。公司公共库不可删。 */
import {
  ModalForm,
  PageContainer,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components'
import { Button, Modal, Popconfirm, Space, Tag, message } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { listUsers, type UserInfo } from '../api/auth'
import { createGrant, listGrants, revokeGrant, type ResourceGrant } from '../api/grants'
import {
  createKnowledgeBase,
  deleteKnowledgeBase,
  listKnowledgeBases,
  updateKnowledgeBase,
  type KnowledgeBase,
} from '../api/knowledgeBases'
import { flattenDepts, getTree } from '../api/org'

const SCOPE_LABEL: Record<string, string> = { company: '公司', department: '部门', personal: '个人' }

export default function KnowledgeBases() {
  const actionRef = useRef<ActionType>(null)
  const [depts, setDepts] = useState<{ value: string; label: string }[]>([])
  const [users, setUsers] = useState<UserInfo[]>([])
  const [grants, setGrants] = useState<{ kb: KnowledgeBase; rows: ResourceGrant[] } | null>(null)
  const reload = () => actionRef.current?.reload()

  useEffect(() => {
    void getTree().then((t) => setDepts(flattenDepts(t)))
    void listUsers().then(setUsers)
  }, [])

  const openGrants = async (kb: KnowledgeBase) => {
    const all = await listGrants({ resource_type: 'knowledge_base' })
    setGrants({ kb, rows: all.filter((g) => g.resource_id === kb.id) })
  }

  const columns: ProColumns<KnowledgeBase>[] = [
    { title: '名称', dataIndex: 'name' },
    { title: '范围', dataIndex: 'scope', render: (_, r) => <Tag>{SCOPE_LABEL[r.scope] ?? r.scope}</Tag> },
    {
      title: '标记', dataIndex: 'is_confidential',
      render: (_, r) => (
        <Space size={4}>
          {r.is_confidential && <Tag color="red">机密</Tag>}
          {r.is_default && <Tag color="blue">公共库</Tag>}
          {!r.is_active && <Tag>停用</Tag>}
        </Space>
      ),
    },
    { title: '文档数', dataIndex: 'file_count', width: 80 },
    {
      title: '操作', valueType: 'option',
      render: (_, r) => [
        <ModalForm
          key="edit"
          title={`编辑 · ${r.name}`}
          trigger={<a>编辑</a>}
          modalProps={{ destroyOnHidden: true }}
          initialValues={{ name: r.name, is_confidential: r.is_confidential, description: r.description, department_id: r.department_id }}
          onFinish={async (v) => {
            await updateKnowledgeBase(r.id, v as { name?: string })
            message.success('已保存')
            reload()
            return true
          }}
        >
          <ProFormText name="name" label="名称" rules={[{ required: true }]} />
          <ProFormSelect name="is_confidential" label="机密" options={[{ value: true, label: '机密（仅本部门子树+授权+admin）' }, { value: false, label: '公开（默认全员可见）' }]} />
          <ProFormSelect name="department_id" label="归属部门" options={depts} tooltip="改部门" />
          <ProFormTextArea name="description" label="描述" />
        </ModalForm>,
        <a
          key="active"
          onClick={async () => {
            await updateKnowledgeBase(r.id, { is_active: !r.is_active })
            message.success(r.is_active ? '已停用' : '已启用')
            reload()
          }}
        >
          {r.is_active ? '停用' : '启用'}
        </a>,
        <a key="grant" onClick={() => openGrants(r)}>授权</a>,
        r.is_default ? (
          <span key="d" style={{ color: '#ccc' }}>删除</span>
        ) : (
          <Popconfirm key="d" title="删除此知识库？（含文档时会被拒）" onConfirm={async () => { await deleteKnowledgeBase(r.id); message.success('已删除'); reload() }}>
            <a style={{ color: '#cf1322' }}>删除</a>
          </Popconfirm>
        ),
      ],
    },
  ]

  return (
    <PageContainer title="知识库集合" subTitle="建库/机密标记/改部门/授权；授权只授内容访问权不授生效权">
      <ProTable<KnowledgeBase>
        rowKey="id"
        actionRef={actionRef}
        columns={columns}
        search={false}
        options={{ reload: true, density: false, setting: false }}
        request={async () => ({ data: await listKnowledgeBases(), success: true })}
        pagination={false}
        toolBarRender={() => [
          <ModalForm
            key="new"
            title="新建知识库"
            trigger={<Button type="primary">新建知识库</Button>}
            modalProps={{ destroyOnHidden: true }}
            onFinish={async (v) => {
              await createKnowledgeBase(v as { name: string; scope: string })
              message.success('已创建')
              reload()
              return true
            }}
          >
            <ProFormText name="name" label="名称" rules={[{ required: true }]} />
            <ProFormSelect name="scope" label="范围" initialValue="department" options={[{ value: 'company', label: '公司（全员）' }, { value: 'department', label: '部门' }]} rules={[{ required: true }]} />
            <ProFormSelect
              name="department_id"
              label="归属部门"
              options={depts}
              tooltip="部门范围时必填"
              dependencies={['scope']}
              rules={[
                ({ getFieldValue }) => ({
                  validator: (_, value) => (
                    getFieldValue('scope') !== 'department' || value
                      ? Promise.resolve()
                      : Promise.reject(new Error('部门范围必须选择归属部门'))
                  ),
                }),
              ]}
            />
            <ProFormSelect name="is_confidential" label="机密" initialValue={false} options={[{ value: false, label: '公开' }, { value: true, label: '机密' }]} />
            <ProFormTextArea name="description" label="描述" />
          </ModalForm>,
        ]}
      />

      <Modal
        open={grants !== null}
        onCancel={() => setGrants(null)}
        title={`授权 · ${grants?.kb.name ?? ''}`}
        footer={null}
        width={640}
      >
        <ModalForm
          title="新增授权"
          trigger={<Button type="primary" size="small" style={{ marginBottom: 12 }}>新增授权</Button>}
          modalProps={{ destroyOnHidden: true }}
          onFinish={async (v: { grantee_type: string; grantee_id: string }) => {
            await createGrant({ resource_type: 'knowledge_base', resource_id: grants!.kb.id, ...v })
            message.success('已授权')
            await openGrants(grants!.kb)
            return true
          }}
        >
          <ProFormSelect name="grantee_type" label="授予对象类型" initialValue="user" options={[{ value: 'user', label: '真人用户' }, { value: 'department', label: '部门（覆盖子树）' }]} rules={[{ required: true }]} />
          <ProFormSelect name="grantee_id" label="授予对象" rules={[{ required: true }]} dependencies={['grantee_type']}
            request={async (p) => (p.grantee_type === 'department' ? depts : users.map((u) => ({ value: u.id, label: u.real_name || u.username })))} />
        </ModalForm>
        {(grants?.rows ?? []).map((g) => (
          <div key={g.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderTop: '1px solid #f0f0f0' }}>
            <Space>
              <Tag>{g.grantee_type === 'department' ? '部门' : g.grantee_type === 'agent' ? 'AI' : '用户'}</Tag>
              <span style={{ fontSize: 12, color: '#666' }}>{g.grantee_id.slice(0, 8)}…</span>
              <Tag color="green">{g.perm}</Tag>
            </Space>
            <Popconfirm title="撤销此授权？" onConfirm={async () => { await revokeGrant(g.id); message.success('已撤销'); await openGrants(grants!.kb) }}>
              <a style={{ color: '#cf1322' }}>撤销</a>
            </Popconfirm>
          </div>
        ))}
        {grants?.rows.length === 0 && <div style={{ color: '#999', paddingTop: 8 }}>暂无授权（默认按 scope 可见）</div>}
      </Modal>
    </PageContainer>
  )
}

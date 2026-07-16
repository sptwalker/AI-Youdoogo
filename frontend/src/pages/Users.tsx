/** 用户管理（仅 admin）：列表 / 新建 / 停用启用。 */
import {
  ModalForm,
  PageContainer,
  ProFormSelect,
  ProFormText,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components'
import { Button, Switch, Tag, Typography, message } from 'antd'
import { useRef } from 'react'
import { createUser, listUsers, ROLE_LABELS, updateUser, type UserInfo } from '../api/auth'

export default function Users() {
  const actionRef = useRef<ActionType>(null)

  const columns: ProColumns<UserInfo>[] = [
    { title: '用户名', dataIndex: 'username' },
    { title: '姓名', dataIndex: 'real_name' },
    {
      title: '角色',
      dataIndex: 'role_code',
      render: (_, row) => <Tag>{ROLE_LABELS[row.role_code]}</Tag>,
    },
    { title: '创建时间', dataIndex: 'create_time', valueType: 'dateTime' },
    {
      title: '飞书身份',
      dataIndex: 'feishu_open_id',
      render: (_, row) => row.feishu_open_id ? (
        <Typography.Text copyable={{ text: row.feishu_open_id }} code>
          {row.feishu_open_id}
        </Typography.Text>
      ) : <Tag>未绑定</Tag>,
    },
    {
      title: '启用',
      dataIndex: 'is_active',
      render: (_, row) => (
        <Switch
          checked={row.is_active}
          onChange={async (checked) => {
            await updateUser(row.id, { is_active: checked })
            message.success(checked ? '已启用' : '已停用')
            actionRef.current?.reload()
          }}
        />
      ),
    },
    {
      title: '操作',
      valueType: 'option',
      render: (_, row) => [
        <ModalForm<{ feishu_open_id?: string }>
          key="feishu"
          title={`飞书身份绑定 · ${row.real_name || row.username}`}
          trigger={<a>绑定 / 更新</a>}
          initialValues={{ feishu_open_id: row.feishu_open_id ?? '' }}
          modalProps={{ destroyOnHidden: true }}
          onFinish={async ({ feishu_open_id }) => {
            await updateUser(row.id, { feishu_open_id: feishu_open_id?.trim() || null })
            message.success(feishu_open_id?.trim() ? '飞书身份已绑定' : '飞书身份已解绑')
            actionRef.current?.reload()
            return true
          }}
        >
          <ProFormText
            name="feishu_open_id"
            label="飞书 open_id"
            tooltip="填写飞书授权用户的不可变 open_id；留空保存可解绑。解绑不会替代停用账号。"
            fieldProps={{ maxLength: 128 }}
            rules={[{ pattern: /^(|ou[-_][A-Za-z0-9_-]+)$/, message: '请输入以 ou_ 或 ou- 开头的 open_id' }]}
          />
        </ModalForm>,
      ],
    },
  ]

  return (
    <PageContainer title="用户管理">
      <ProTable<UserInfo>
        rowKey="id"
        actionRef={actionRef}
        search={false}
        columns={columns}
        request={async () => {
          const users = await listUsers()
          return { data: users, success: true }
        }}
        toolBarRender={() => [
          <ModalForm<{
            username: string
            password: string
            real_name?: string
            role_code: string
            feishu_open_id?: string
          }>
            key="create"
            title="新建用户"
            trigger={<Button type="primary">新建用户</Button>}
            modalProps={{ destroyOnHidden: true }}
            onFinish={async (values) => {
              await createUser(values)
              message.success('已创建')
              actionRef.current?.reload()
              return true
            }}
          >
            <ProFormText
              name="username"
              label="用户名"
              rules={[
                { required: true },
                { pattern: /^[a-zA-Z0-9_.-]+$/, message: '仅限字母/数字/_.-' },
              ]}
            />
            <ProFormText.Password
              name="password"
              label="初始密码"
              rules={[{ required: true, min: 8, message: '至少8位' }]}
            />
            <ProFormText name="real_name" label="姓名" />
            <ProFormText
              name="feishu_open_id"
              label="飞书 open_id（可选）"
              tooltip="只绑定管理员核验过的飞书 open_id；系统不会在首次登录时自动创建用户。"
              rules={[{ pattern: /^(|ou[-_][A-Za-z0-9_-]+)$/, message: '请输入以 ou_ 或 ou- 开头的 open_id' }]}
            />
            <ProFormSelect
              name="role_code"
              label="角色"
              initialValue="member"
              options={Object.entries(ROLE_LABELS).map(([value, label]) => ({ value, label }))}
            />
          </ModalForm>,
        ]}
      />
    </PageContainer>
  )
}

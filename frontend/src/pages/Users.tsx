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
import { Button, Popconfirm, Switch, Tag, Typography, message } from 'antd'
import { useRef } from 'react'
import {
  createUser,
  listUsers,
  ROLE_LABELS,
  updateUser,
  type UserInfo,
} from '../api/auth'
import {
  normalizeUserCreateValues,
  validateOptionalFeishuOpenId,
  type UserCreateFormValues,
} from './userForm'

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
      render: (_, row) =>
        row.is_active ? (
          // 停用不可逆(用户将无法登录),二次确认;启用无风险,直接切换。
          <Popconfirm
            title="确认停用该用户?"
            description="停用后该用户将无法登录。"
            okText="停用"
            okButtonProps={{ danger: true }}
            cancelText="取消"
            onConfirm={async () => {
              await updateUser(row.id, { is_active: false })
              message.success('已停用')
              actionRef.current?.reload()
            }}
          >
            <Switch checked />
          </Popconfirm>
        ) : (
          <Switch
            checked={false}
            onChange={async () => {
              await updateUser(row.id, { is_active: true })
              message.success('已启用')
              actionRef.current?.reload()
            }}
          />
        ),
    },
    {
      title: '操作',
      valueType: 'option',
      render: (_, row) => [
        <ModalForm<{ role_code: UserInfo['role_code'] }>
          key="role"
          title={`调整角色 · ${row.real_name || row.username}`}
          trigger={<a>调整角色</a>}
          initialValues={{ role_code: row.role_code }}
          modalProps={{ destroyOnHidden: true }}
          onFinish={async ({ role_code }) => {
            await updateUser(row.id, { role_code })
            message.success('角色已更新')
            actionRef.current?.reload()
            return true
          }}
        >
          <ProFormSelect
            name="role_code"
            label="系统角色"
            rules={[{ required: true }]}
            options={Object.entries(ROLE_LABELS).map(([value, label]) => ({ value, label }))}
          />
        </ModalForm>,
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
            rules={[
              { validator: (_, value) => validateOptionalFeishuOpenId(value as string | undefined) },
            ]}
          />
        </ModalForm>,
        <ModalForm<{ password: string }>
          key="reset-pwd"
          title={`重置密码 · ${row.real_name || row.username}`}
          trigger={<a>重置密码</a>}
          modalProps={{ destroyOnHidden: true }}
          onFinish={async ({ password }) => {
            await updateUser(row.id, { password })
            message.success('密码已重置')
            return true
          }}
        >
          <ProFormText.Password
            name="password"
            label="新密码"
            fieldProps={{ maxLength: 128 }}
            rules={[
              { required: true, min: 8, message: '至少8位' },
              { max: 128, message: '最多128位' },
            ]}
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
          <ModalForm<UserCreateFormValues>
            key="create"
            title="新建用户"
            trigger={<Button type="primary">新建用户</Button>}
            modalProps={{ destroyOnHidden: true }}
            onFinish={async (values) => {
              await createUser(normalizeUserCreateValues(values))
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
                { min: 2, message: '至少2位' },
                { max: 64, message: '最多64位' },
                { pattern: /^[a-zA-Z0-9_.-]+$/, message: '仅限字母/数字/_.-' },
              ]}
            />
            <ProFormText.Password
              name="password"
              label="初始密码"
              fieldProps={{ maxLength: 128 }}
              rules={[
                { required: true, min: 8, message: '至少8位' },
                { max: 128, message: '最多128位' },
              ]}
            />
            <ProFormText
              name="real_name"
              label="姓名"
              fieldProps={{ maxLength: 64 }}
              rules={[{ max: 64, message: '最多64位' }]}
            />
            <ProFormText
              name="feishu_open_id"
              label="飞书 open_id（可选）"
              tooltip="填写当前应用内稳定的飞书 open_id 完成预绑定；未绑定身份不能登录，也不会自动开户。"
              fieldProps={{ maxLength: 128 }}
              rules={[
                { validator: (_, value) => validateOptionalFeishuOpenId(value as string | undefined) },
              ]}
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

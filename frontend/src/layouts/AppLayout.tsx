/** 应用主布局：ProLayout + 菜单 + 当前用户/退出。 */
import { LogoutOutlined } from '@ant-design/icons'
import { ProLayout } from '@ant-design/pro-components'
import { Dropdown } from 'antd'
import { useEffect, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { fetchMe, ROLE_LABELS, type UserInfo } from '../api/auth'
import { TOKEN_KEY } from '../api/client'

const BIZ_ROUTES = [
  { path: '/knowledge', name: '知识库' },
  { path: '/discussion', name: '协作空间' },
  { path: '/agents', name: '智能体' },
  { path: '/tasks', name: '任务卡' },
  { path: '/proposals', name: '提案' },
  { path: '/meetings', name: '会议会商' },
  { path: '/ops-board', name: '运营看板' },
]
const ADMIN_ROUTES = [
  { path: '/org', name: '组织架构' },
  { path: '/users', name: '用户与权限' },
  { path: '/knowledge-bases', name: '知识库集合' },
  { path: '/data-sources', name: '数据接口' },
  { path: '/system-config', name: '系统配置' },
  { path: '/audit-log', name: '系统日志' },
]

/** 菜单二级分组：工作桌面置顶 + 业务组 + 系统管理组（仅 admin 可见）。
 *  注意：ProLayout 用 path 作菜单 key，分组父节点也必须有 path，否则整组不渲染。 */
function buildMenu(isAdmin: boolean) {
  return {
    path: '/',
    routes: [
      { path: '/', name: '工作桌面' },
      { path: '/g-biz', name: '业务', routes: BIZ_ROUTES },
      ...(isAdmin ? [{ path: '/g-sys', name: '系统管理', routes: ADMIN_ROUTES }] : []),
    ],
  }
}

export default function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const [me, setMe] = useState<UserInfo | null>(null)

  useEffect(() => {
    fetchMe().then(setMe).catch(() => {})
  }, [])

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY)
    navigate('/login', { replace: true })
  }

  return (
    <ProLayout
      title="创想悦动AI决策大脑"
      layout="side"
      menu={{ defaultOpenAll: true }}
      route={buildMenu(me?.role_code === 'admin')}
      location={{ pathname: location.pathname }}
      menuItemRender={(item, dom) => (
        <a onClick={() => item.path && navigate(item.path)}>{dom}</a>
      )}
      avatarProps={{
        title: me ? `${me.real_name || me.username}（${ROLE_LABELS[me.role_code]}）` : '…',
        size: 'small',
        render: (_, dom) => (
          <Dropdown
            menu={{
              items: [{ key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: logout }],
            }}
          >
            {dom}
          </Dropdown>
        ),
      }}
    >
      <Outlet context={{ me }} />
    </ProLayout>
  )
}

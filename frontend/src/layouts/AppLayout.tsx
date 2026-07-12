/** 应用主布局：ProLayout + 菜单 + 当前用户/退出。 */
import { LogoutOutlined } from '@ant-design/icons'
import { ProLayout } from '@ant-design/pro-components'
import { Dropdown } from 'antd'
import { useEffect, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { fetchMe, ROLE_LABELS, type UserInfo } from '../api/auth'
import { TOKEN_KEY } from '../api/client'

const MENU = {
  path: '/',
  routes: [
    { path: '/', name: '工作台' },
    { path: '/knowledge', name: '知识库' },
    { path: '/ops-board', name: '运营看板' },
    { path: '/agents', name: '智能体' },
    { path: '/tasks', name: '任务卡' },
    { path: '/users', name: '用户管理' },
  ],
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
      layout="mix"
      route={MENU}
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

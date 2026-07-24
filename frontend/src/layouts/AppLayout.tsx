/** 应用主布局：ProLayout + 菜单 + 当前用户/退出。 */
import { LogoutOutlined } from '@ant-design/icons'
import { ProLayout } from '@ant-design/pro-components'
import { Button, Dropdown, Result, Spin } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { Link, Outlet, useLocation, useMatches, useNavigate } from 'react-router-dom'
import { fetchMe, ROLE_LABELS, type UserInfo } from '../api/auth'
import { TOKEN_KEY } from '../api/client'
import { routeAllowsRole } from '../auth/authorization'

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
  { path: '/semantic-terms', name: '业务术语字典' },
  { path: '/ai-providers', name: 'AI 配置' },
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
  const matches = useMatches()
  const [me, setMe] = useState<UserInfo | null>(null)
  const [meLoading, setMeLoading] = useState(true)
  const [meError, setMeError] = useState(false)

  const loadMe = useCallback(async () => {
    setMeLoading(true)
    setMeError(false)
    try {
      setMe(await fetchMe())
    } catch {
      setMe(null)
      setMeError(true)
    } finally {
      setMeLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadMe()
  }, [loadMe])

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY)
    navigate('/login', { replace: true })
  }

  if (meLoading) {
    return <Spin fullscreen tip="正在加载当前用户与权限…" />
  }

  if (meError || !me) {
    return (
      <Result
        status="error"
        title="无法加载当前用户权限"
        subTitle="系统没有把权限查询失败降级为普通用户。请重试；若仍失败，请退出后重新登录。"
        extra={[
          <Button key="retry" type="primary" onClick={() => void loadMe()}>重试</Button>,
          <Button key="logout" onClick={logout}>退出登录</Button>,
        ]}
      />
    )
  }

  const routeAllowed = routeAllowsRole(me.role_code, matches.map((match) => match.handle))

  return (
    <ProLayout
      title="创想悦动AI决策大脑"
      layout="side"
      menu={{ defaultOpenAll: true }}
      route={buildMenu(me.role_code === 'admin')}
      location={{ pathname: location.pathname }}
      menuItemRender={(item, dom) => (
        item.path && !item.isUrl
          ? <Link to={item.path} onClick={item.onClick}>{dom}</Link>
          : dom
      )}
      avatarProps={{
        title: `${me.real_name || me.username}（${ROLE_LABELS[me.role_code]}）`,
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
      {routeAllowed ? (
        <Outlet context={{ me }} />
      ) : (
        <Result
          status="403"
          title="无权访问此页面"
          subTitle="当前账号没有该管理功能的访问权限。"
          extra={<Button type="primary" onClick={() => navigate('/', { replace: true })}>返回工作桌面</Button>}
        />
      )}
    </ProLayout>
  )
}

/** 登录页：保留账号密码，并提供飞书 OAuth 一次性交换登录。 */
import {
  BarChartOutlined,
  LockOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { LoginForm, ProFormText } from '@ant-design/pro-components'
import { Button, Divider, Space, Tag, Typography, message } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  exchangeFeishuLogin,
  fetchFeishuStatus,
  login,
  startFeishuLogin,
} from '../api/auth'
import { TOKEN_KEY } from '../api/client'

export default function Login() {
  const navigate = useNavigate()
  const exchangeStarted = useRef(false)
  const [feishuEnabled, setFeishuEnabled] = useState<boolean | null>(null)

  useEffect(() => {
    fetchFeishuStatus()
      .then(({ enabled }) => setFeishuEnabled(enabled))
      .catch(() => setFeishuEnabled(false))
  }, [])

  useEffect(() => {
    const result = new URLSearchParams(window.location.search).get('feishu')
    if (!result || exchangeStarted.current) return
    exchangeStarted.current = true
    window.history.replaceState({}, '', '/login')

    if (result === 'success') {
      void exchangeFeishuLogin().then((token) => {
        localStorage.setItem(TOKEN_KEY, token.access_token)
        navigate(token.redirect_to || '/', { replace: true })
      }).catch(() => {})
      return
    }
    const messages: Record<string, string> = {
      cancelled: '已取消飞书授权，您仍可使用账号密码登录。',
      access_required: '当前飞书账号暂无系统访问权限，请联系管理员完成账号授权或状态确认。',
      invalid_state: '本次飞书登录已失效，请重新发起登录。',
      unavailable: '飞书登录暂不可用，请联系管理员。',
      error: '飞书认证未完成，请稍后重试或使用账号密码登录。',
    }
    message[result === 'cancelled' ? 'info' : 'error'](messages[result] ?? messages.error)
  }, [navigate])

  const onFinish = async (values: { username: string; password: string }) => {
    const token = await login(values.username, values.password)
    localStorage.setItem(TOKEN_KEY, token.access_token)
    navigate('/', { replace: true })
    return true
  }

  return (
    <div className="login-page">
      <main className="login-shell">
        <section className="login-context" aria-label="产品介绍">
          <Tag className="login-eyebrow">企业 AI 决策工作空间</Tag>
          <Typography.Title level={1}>让经营信息汇聚成可执行的管理判断</Typography.Title>
          <Typography.Paragraph>
            围绕知识、运营、任务与会商，把 AI 的分析能力放进清晰、可追溯、由真人确认的决策流程。
          </Typography.Paragraph>
          <Space direction="vertical" size={18} className="login-capabilities">
            <span><BarChartOutlined /> 经营态势与关键指标集中呈现</span>
            <span><TeamOutlined /> 跨部门协作与决策过程全程留痕</span>
            <span><SafetyCertificateOutlined /> 权限沿用系统角色与资源授权，不由登录方式改变</span>
          </Space>
        </section>

        <section className="login-panel" aria-label="登录">
          <div className="login-card">
            <LoginForm
              title="进入决策工作台"
              subTitle="创想悦动 AI 决策大脑"
              onFinish={onFinish}
              submitter={{
                searchConfig: { submitText: '账号密码登录' },
                submitButtonProps: { size: 'large', block: true },
                render: (_, dom) => [
                  ...dom,
                  <Divider key="divider" plain>或使用企业身份</Divider>,
                  <Button
                    key="feishu"
                    className="feishu-login-button"
                    size="large"
                    block
                    htmlType="button"
                    loading={feishuEnabled === null}
                    disabled={feishuEnabled === false}
                    onClick={() => startFeishuLogin('/')}
                    icon={<span className="feishu-mark">飞</span>}
                  >
                    {feishuEnabled === false ? '飞书登录暂未启用' : '飞书登录'}
                  </Button>,
                ],
              }}
            >
              <ProFormText
                name="username"
                fieldProps={{ size: 'large', prefix: <UserOutlined /> }}
                placeholder="用户名"
                rules={[{ required: true, message: '请输入用户名' }]}
              />
              <ProFormText.Password
                name="password"
                fieldProps={{ size: 'large', prefix: <LockOutlined /> }}
                placeholder="密码"
                rules={[{ required: true, message: '请输入密码' }]}
              />
            </LoginForm>
            <Typography.Text type="secondary" className="login-access-note">
              飞书登录仅用于身份验证；系统角色与数据权限仍由管理员预先配置。
            </Typography.Text>
          </div>
        </section>
      </main>
    </div>
  )
}

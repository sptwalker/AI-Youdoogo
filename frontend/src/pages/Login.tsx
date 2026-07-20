/** 登录页：用户名+密码 或 飞书扫码 → 存 token → 进工作台。 */
import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { LoginForm, ProFormText } from '@ant-design/pro-components'
import { Button, Divider, message } from 'antd'
import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { feishuCallback, feishuLoginUrl, login } from '../api/auth'
import { TOKEN_KEY } from '../api/client'

export default function Login() {
  const navigate = useNavigate()

  // 飞书回调：URL 带 code 时用它换令牌登录（I2）
  useEffect(() => {
    const code = new URLSearchParams(window.location.search).get('code')
    if (!code) return
    feishuCallback(code)
      .then((token) => {
        localStorage.setItem(TOKEN_KEY, token.access_token)
        navigate('/', { replace: true })
      })
      .catch(() => message.error('飞书登录失败，请重试或用账号密码登录'))
  }, [navigate])

  const onFinish = async (values: { username: string; password: string }) => {
    const token = await login(values.username, values.password)
    localStorage.setItem(TOKEN_KEY, token.access_token)
    navigate('/', { replace: true })
    return true
  }

  const onFeishuLogin = async () => {
    // 回调回到登录页本身（带 code），由上面的 useEffect 接管
    const redirect = `${window.location.origin}/login`
    const { url } = await feishuLoginUrl(redirect)
    window.location.href = url
  }

  return (
    <div style={{ height: '100vh', display: 'flex', alignItems: 'center', background: '#f5f5f5' }}>
      <LoginForm
        title="创想悦动 AI 决策大脑"
        subTitle="企业智能业务处理与辅助决策管理系统"
        onFinish={onFinish}
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
        <Divider plain style={{ color: '#999', fontSize: 12 }}>或</Divider>
        <Button block size="large" onClick={onFeishuLogin}>飞书扫码登录</Button>
      </LoginForm>
    </div>
  )
}

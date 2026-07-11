/** 登录页：用户名+密码 → 存 token → 进工作台。 */
import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { LoginForm, ProFormText } from '@ant-design/pro-components'
import { useNavigate } from 'react-router-dom'
import { login } from '../api/auth'
import { TOKEN_KEY } from '../api/client'

export default function Login() {
  const navigate = useNavigate()

  const onFinish = async (values: { username: string; password: string }) => {
    const token = await login(values.username, values.password)
    localStorage.setItem(TOKEN_KEY, token.access_token)
    navigate('/', { replace: true })
    return true
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
      </LoginForm>
    </div>
  )
}

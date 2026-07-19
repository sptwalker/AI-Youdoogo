/** 登录页：账号密码登录。 */
import {
  BarChartOutlined,
  LockOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { LoginForm, ProFormText } from '@ant-design/pro-components'
import { Space, Tag, Typography } from 'antd'
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
              使用管理员分配的账号登录。
            </Typography.Text>
          </div>
        </section>
      </main>
    </div>
  )
}

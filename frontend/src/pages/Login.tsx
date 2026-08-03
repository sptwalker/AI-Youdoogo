/** 登录页：保留账号密码，并完成飞书 OAuth 的状态展示与一次性交换。 */
import {
  BarChartOutlined,
  LockOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { LoginForm, ProFormCheckbox, ProFormText } from '@ant-design/pro-components'
import { Alert, Button, Divider, Space, Tag, Typography } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { exchangeFeishuLogin, fetchFeishuStatus, login, startFeishuLogin } from '../api/auth'
import { ApiError, setToken } from '../api/http'
import { normalizeAppPath } from '../auth/paths'

const FEISHU_RETURN_TO_KEY = 'youdoo_feishu_return_to'

const CALLBACK_MESSAGES: Record<string, { type: 'error' | 'info'; message: string }> = {
  cancelled: { type: 'info', message: '已取消飞书授权，您仍可使用账号密码登录。' },
  access_required: {
    type: 'error',
    message: '当前飞书账号暂无系统访问权限，请联系管理员完成账号预绑定或状态确认。',
  },
  invalid_state: { type: 'error', message: '本次飞书登录已失效，请重新发起登录。' },
  unavailable: { type: 'error', message: '飞书登录暂不可用，请联系管理员。' },
  error: { type: 'error', message: '飞书认证未完成，请稍后重试或使用账号密码登录。' },
}

type FeishuAvailability = 'loading' | 'enabled' | 'disabled' | 'unavailable'
type LoginFeedback = { type: 'error' | 'info'; message: string } | null

export default function Login() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const exchangeStarted = useRef(false)
  const callbackResult = searchParams.get('feishu')
  const storedReturnTo = callbackResult ? sessionStorage.getItem(FEISHU_RETURN_TO_KEY) : null
  const returnTo = normalizeAppPath(searchParams.get('return_to') ?? storedReturnTo)
  const [feishuAvailability, setFeishuAvailability] = useState<FeishuAvailability>('loading')
  const [completingFeishu, setCompletingFeishu] = useState(callbackResult === 'success')
  const [feedback, setFeedback] = useState<LoginFeedback>(
    searchParams.get('expired') === '1'
      ? { type: 'error', message: '登录状态已过期，请重新登录。' }
      : null,
  )

  useEffect(() => {
    fetchFeishuStatus()
      .then(({ enabled }) => setFeishuAvailability(enabled ? 'enabled' : 'disabled'))
      .catch(() => setFeishuAvailability('unavailable'))
  }, [])

  useEffect(() => {
    if (!callbackResult || exchangeStarted.current) return
    exchangeStarted.current = true
    window.history.replaceState({}, '', '/login')

    if (callbackResult !== 'success') {
      setFeedback(CALLBACK_MESSAGES[callbackResult] ?? CALLBACK_MESSAGES.error)
      setCompletingFeishu(false)
      return
    }

    setFeedback({ type: 'info', message: '飞书身份已验证，正在完成系统登录…' })
    void exchangeFeishuLogin()
      .then((token) => {
        setToken(token.access_token, true)
        sessionStorage.removeItem(FEISHU_RETURN_TO_KEY)
        navigate(normalizeAppPath(token.redirect_to), { replace: true })
      })
      .catch(() => {
        setFeedback({ type: 'error', message: '登录凭证交换失败或已失效，请重新使用飞书登录。' })
        setCompletingFeishu(false)
      })
  }, [callbackResult, navigate])

  const onFinish = async (values: { username: string; password: string; remember?: boolean }) => {
    setFeedback(null)
    try {
      const token = await login(values.username, values.password)
      setToken(token.access_token, values.remember ?? true)
      sessionStorage.removeItem(FEISHU_RETURN_TO_KEY)
      navigate(returnTo, { replace: true })
      return true
    } catch (error) {
      setFeedback({
        type: 'error',
        message: error instanceof ApiError ? error.message : '登录失败，请稍后重试',
      })
      return false
    }
  }

  const beginFeishuLogin = () => {
    sessionStorage.setItem(FEISHU_RETURN_TO_KEY, returnTo)
    startFeishuLogin(returnTo)
  }

  const feishuButtonText = {
    loading: '正在检查飞书登录状态',
    enabled: '飞书登录',
    disabled: '飞书登录暂未启用',
    unavailable: '飞书登录状态不可用',
  }[feishuAvailability]

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
              <ProFormCheckbox name="remember" initialValue={true}>
                记住登录（公用电脑请勿勾选）
              </ProFormCheckbox>
            </LoginForm>
            <Divider plain>或使用企业身份</Divider>
            <Button
              className="feishu-login-button"
              size="large"
              block
              htmlType="button"
              loading={feishuAvailability === 'loading' || completingFeishu}
              disabled={feishuAvailability !== 'enabled' || completingFeishu}
              onClick={beginFeishuLogin}
              icon={<span className="feishu-mark">飞</span>}
            >
              {completingFeishu ? '正在完成飞书登录' : feishuButtonText}
            </Button>
            {feedback && <Alert className="login-feedback" showIcon type={feedback.type} message={feedback.message} />}
            <Typography.Text type="secondary" className="login-access-note">
              飞书仅验证身份；管理员预绑定本地账号后，登录会沿用该账号的系统角色与资源权限。
            </Typography.Text>
          </div>
        </section>
      </main>
    </div>
  )
}

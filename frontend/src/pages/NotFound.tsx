import { Button, Result } from 'antd'
import { useNavigate } from 'react-router-dom'

export default function NotFound() {
  const navigate = useNavigate()
  return (
    <Result
      status="404"
      title="页面不存在"
      subTitle="地址可能已变更，或该功能尚未开放。"
      extra={<Button type="primary" onClick={() => navigate('/', { replace: true })}>返回工作桌面</Button>}
    />
  )
}

/** 工作台：占位页，阶段2 接运营看板。 */
import { PageContainer } from '@ant-design/pro-components'
import { Card, Typography } from 'antd'

export default function Dashboard() {
  return (
    <PageContainer title="工作台">
      <Card>
        <Typography.Title level={4}>欢迎使用创想悦动 AI 决策大脑系统</Typography.Title>
        <Typography.Paragraph type="secondary">
          阶段2 将在此接入平台运营部数据看板（日活趋势、异常告警、AI 日报与提案）。
        </Typography.Paragraph>
      </Card>
    </PageContainer>
  )
}

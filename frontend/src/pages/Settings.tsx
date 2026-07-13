/** 系统设置（仅 admin·超级管理员）：公司骨架初始化等重操作集中在此，避免误触。
 *  未来 AI API / 飞书 / 数据接口 / 权限 / 系统日志等系统级配置也归入本页（F4/F5）。 */
import { PageContainer } from '@ant-design/pro-components'
import { Alert, Button, Card, Popconfirm, Space, Typography, message } from 'antd'
import { initTemplate } from '../api/org'

export default function Settings() {
  return (
    <PageContainer title="系统设置" subTitle="超级管理员">
      <Card title="组织骨架" style={{ maxWidth: 720 }}>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Typography.Paragraph type="secondary">
            按公司模板初始化组织骨架：公司根节点 + 8 个一级部门 + 8 位公司顾问（含 CCO）+ 9 位总监助理。
            操作<strong>幂等可重跑</strong>——已存在的按编码更新、缺失的补齐，不会重复创建；被删除的模板岗位会被补回。
          </Typography.Paragraph>
          <Alert
            type="info"
            showIcon
            message="这是重操作，已从「组织架构」页移到此处集中管理，避免误触。"
          />
          <Popconfirm
            title="确认按模板初始化/补齐公司骨架？"
            description="幂等操作：更新已有、补齐缺失，不会重复创建。"
            okText="确认初始化"
            onConfirm={async () => {
              const r = await initTemplate()
              message.success(
                `已初始化：${r.departments} 部门 / ${r.execs} 顾问 / ${r.directors} 总监助理`,
              )
            }}
          >
            <Button type="primary">一键初始化 / 补齐公司骨架</Button>
          </Popconfirm>
        </Space>
      </Card>

      <Card title="更多系统配置" style={{ maxWidth: 720, marginTop: 16 }}>
        <Typography.Paragraph type="secondary">
          AI API 配置、飞书配置、数据接口、用户权限、系统日志等系统级配置将在后续阶段（F4/F5）陆续归入本页。
        </Typography.Paragraph>
      </Card>
    </PageContainer>
  )
}

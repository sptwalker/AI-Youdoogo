/** 真人工作台：把三个红线确认闸门（待验收任务/待评审提案/待确认决议）聚合到落地页。
 *  动作全复用既有端点（transitionTask/reviewProposal/confirmResolution）。 */
import { ModalForm, PageContainer, ProFormSelect, ProFormTextArea } from '@ant-design/pro-components'
import { Badge, Card, Col, Empty, List, Popconfirm, Row, Tag, Typography, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { reviewProposal } from '../api/proposals'
import { confirmResolution } from '../api/meetings'
import { transitionTask } from '../api/tasks'
import { getWorkbench, type Workbench } from '../api/workbench'

const PRIORITY_COLOR: Record<string, string> = { high: 'red', normal: 'blue', low: 'default' }

export default function Dashboard() {
  const [data, setData] = useState<Workbench | null>(null)
  const reload = useCallback(async () => setData(await getWorkbench()), [])
  useEffect(() => {
    void reload()
  }, [reload])

  const act = async (fn: () => Promise<unknown>, okMsg: string) => {
    await fn()
    message.success(okMsg)
    await reload()
  }

  const c = data?.counts ?? { tasks: 0, proposals: 0, resolutions: 0 }

  return (
    <PageContainer
      title="工作台"
      subTitle="待我确认（红线：一切生效动作须真人确认）"
    >
      <Row gutter={16}>
        <Col xs={24} lg={8}>
          <Card title={<Badge count={c.tasks} showZero offset={[10, 0]}>待验收任务</Badge>}>
            {data && data.tasks.length === 0 && <Empty description="无待验收任务" />}
            <List
              dataSource={data?.tasks ?? []}
              renderItem={(t) => (
                <List.Item
                  actions={[
                    <Popconfirm
                      key="ok"
                      title="确认验收此任务？"
                      onConfirm={() => act(() => transitionTask(t.id, 'accepted'), '已验收')}
                    >
                      <a>验收</a>
                    </Popconfirm>,
                    <Popconfirm
                      key="no"
                      title="驳回此任务？"
                      onConfirm={() => act(() => transitionTask(t.id, 'rejected'), '已驳回')}
                    >
                      <a style={{ color: '#cf1322' }}>驳回</a>
                    </Popconfirm>,
                  ]}
                >
                  <List.Item.Meta
                    title={t.title}
                    description={<Tag color={PRIORITY_COLOR[t.priority]}>{t.task_type}</Tag>}
                  />
                </List.Item>
              )}
            />
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card title={<Badge count={c.proposals} showZero offset={[10, 0]}>待评审提案</Badge>}>
            {data && data.proposals.length === 0 && <Empty description="无待评审提案" />}
            <List
              dataSource={data?.proposals ?? []}
              renderItem={(p) => (
                <List.Item
                  actions={[
                    <ModalForm<{ decision: 'approve' | 'reject'; conclusion: string }>
                      key="rv"
                      title={`评审提案 ${p.code}`}
                      trigger={<a>评审</a>}
                      modalProps={{ destroyOnHidden: true }}
                      onFinish={async (v) => {
                        await act(() => reviewProposal(p.id, v.decision, v.conclusion), '已评审')
                        return true
                      }}
                    >
                      <ProFormSelect
                        name="decision"
                        label="决定"
                        initialValue="approve"
                        options={[
                          { value: 'approve', label: '通过' },
                          { value: 'reject', label: '驳回' },
                        ]}
                        rules={[{ required: true }]}
                      />
                      <ProFormTextArea name="conclusion" label="评审意见" rules={[{ required: true }]} />
                    </ModalForm>,
                  ]}
                >
                  <List.Item.Meta
                    title={p.title}
                    description={<Tag color={PRIORITY_COLOR[p.priority]}>{p.code}</Tag>}
                  />
                </List.Item>
              )}
            />
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card title={<Badge count={c.resolutions} showZero offset={[10, 0]}>待确认决议</Badge>}>
            {data && data.resolutions.length === 0 && <Empty description="无待确认决议" />}
            <List
              dataSource={data?.resolutions ?? []}
              renderItem={(r) => (
                <List.Item
                  actions={[
                    <Popconfirm
                      key="ok"
                      title="确认此决议生效？（红线动作）"
                      onConfirm={() => act(() => confirmResolution(r.id), '决议已确认生效')}
                    >
                      <a>确认生效</a>
                    </Popconfirm>,
                  ]}
                >
                  <Typography.Text style={{ whiteSpace: 'pre-wrap' }}>
                    {r.content}
                    {r.due_date && <Tag style={{ marginLeft: 8 }}>截止 {r.due_date}</Tag>}
                  </Typography.Text>
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>
    </PageContainer>
  )
}

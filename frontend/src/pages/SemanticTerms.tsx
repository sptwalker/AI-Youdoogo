/** 业务术语字典（统一语义层，仅 admin）：两栏式 master-detail。
 *  左列术语列表（点选），右列详情编辑面板（建/改/删）。字号 10px。
 *  用途：统一跨部门口径（注入 AI 提示词）+ 别名查询扩展（喂关键词臂）。仅口径参考，不触发决议。 */
import { PageContainer } from '@ant-design/pro-components'
import {
  Button,
  Card,
  Col,
  ConfigProvider,
  Empty,
  Form,
  Input,
  List,
  Popconfirm,
  Row,
  Select,
  Space,
  Tag,
  message,
} from 'antd'
import { useEffect, useState } from 'react'
import {
  createTerm,
  deleteTerm,
  listTerms,
  updateTerm,
  type SemanticTerm,
  type TermInput,
} from '../api/semantic'

const TYPE_LABEL: Record<string, string> = { metric: '指标', dimension: '维度', entity: '实体' }
const TYPE_COLOR: Record<string, string> = { metric: 'blue', dimension: 'green', entity: 'gold' }
const TYPE_OPTIONS = [
  { value: 'metric', label: '指标' },
  { value: 'dimension', label: '维度' },
  { value: 'entity', label: '实体' },
]

/** 表单值：别名用逗号/顿号分隔的字符串，提交时拆成数组。 */
type FormVals = {
  canonical_name: string
  aliases?: string
  term_type: TermInput['term_type']
  definition?: string
  linked_view?: string
  sql_template?: string
}

const splitAliases = (s?: string): string[] =>
  (s ?? '').split(/[,，、\s]+/).map((x) => x.trim()).filter(Boolean)

const toPayload = (v: FormVals): Partial<TermInput> => ({
  canonical_name: v.canonical_name,
  aliases: splitAliases(v.aliases),
  term_type: v.term_type,
  definition: v.definition || null,
  linked_view: v.linked_view || null,
  sql_template: v.sql_template || null,
})

const toForm = (t: SemanticTerm): FormVals => ({
  canonical_name: t.canonical_name,
  aliases: t.aliases.join('、'),
  term_type: t.term_type,
  definition: t.definition ?? undefined,
  linked_view: t.linked_view ?? undefined,
  sql_template: t.sql_template ?? undefined,
})

const BLANK: FormVals = { canonical_name: '', term_type: 'metric' }

export default function SemanticTerms() {
  const [terms, setTerms] = useState<SemanticTerm[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)  // null=新建态
  const [form] = Form.useForm<FormVals>()

  const load = async () => {
    const rows = await listTerms()
    setTerms(rows)
    return rows
  }
  useEffect(() => {
    void load()
  }, [])

  const pick = (t: SemanticTerm) => {
    setSelectedId(t.id)
    form.setFieldsValue(toForm(t))
  }
  const startNew = () => {
    setSelectedId(null)
    form.setFieldsValue(BLANK)
  }

  const onSave = async (v: FormVals) => {
    if (selectedId) {
      const u = await updateTerm(selectedId, toPayload(v))
      message.success('已保存')
      await load()
      setSelectedId(u.id)
    } else {
      const c = await createTerm(toPayload(v))
      message.success('已创建')
      await load()
      setSelectedId(c.id)
      form.setFieldsValue(toForm(c))
    }
  }

  const onDelete = async () => {
    if (!selectedId) return
    await deleteTerm(selectedId)
    message.success('已删除')
    await load()
    startNew()
  }

  return (
    <PageContainer
      title="业务术语字典"
      subTitle="统一跨部门口径：注入 AI 提示词 + 别名查询扩展。仅口径参考，不触发业务决议"
    >
      <ConfigProvider theme={{ token: { fontSize: 10 } }}>
        <Row gutter={16}>
          {/* 左栏：术语列表 */}
          <Col xs={24} md={9}>
            <Card
              size="small"
              title={`术语（${terms.length}）`}
              extra={<Button type="primary" size="small" onClick={startNew}>+ 新建</Button>}
              styles={{ body: { maxHeight: 'calc(100vh - 220px)', overflowY: 'auto', padding: 0 } }}
            >
              <List
                size="small"
                dataSource={terms}
                locale={{ emptyText: <Empty description="暂无术语" /> }}
                renderItem={(t) => (
                  <List.Item
                    onClick={() => pick(t)}
                    style={{
                      cursor: 'pointer', padding: '8px 12px',
                      background: t.id === selectedId ? '#e6f4ff' : undefined,
                    }}
                  >
                    <Space size={6} wrap>
                      <Tag color={TYPE_COLOR[t.term_type]}>{TYPE_LABEL[t.term_type] ?? t.term_type}</Tag>
                      <span>{t.canonical_name}</span>
                      {t.aliases.length > 0 && (
                        <span style={{ color: '#999' }}>· {t.aliases.join('、')}</span>
                      )}
                    </Space>
                  </List.Item>
                )}
              />
            </Card>
          </Col>

          {/* 右栏：详情编辑 */}
          <Col xs={24} md={15}>
            <Card size="small" title={selectedId ? '编辑术语' : '新建术语'}>
              <Form<FormVals>
                form={form}
                layout="vertical"
                initialValues={BLANK}
                onFinish={onSave}
              >
                <Form.Item
                  name="canonical_name" label="规范名"
                  tooltip="全公司统一口径的标准称呼，如「累计激活设备数」"
                  rules={[{ required: true, message: '规范名必填' }]}
                >
                  <Input placeholder="累计激活设备数" />
                </Form.Item>
                <Form.Item
                  name="aliases" label="别名/同义词"
                  tooltip="逗号或顿号分隔，如「新增设备、激活量」。查询命中别名会映射到规范名"
                >
                  <Input placeholder="新增设备、激活量" />
                </Form.Item>
                <Form.Item name="term_type" label="类型" rules={[{ required: true }]}>
                  <Select options={TYPE_OPTIONS} />
                </Form.Item>
                <Form.Item name="definition" label="口径定义" tooltip="一句话说清算法/边界">
                  <Input.TextArea rows={2} placeholder="new_device 事件按 device_id 去重，跨全部日期" />
                </Form.Item>
                <Form.Item name="linked_view" label="关联数据源" tooltip="指标类可填 TD 视图名，如 v_event_4">
                  <Input placeholder="v_event_4" />
                </Form.Item>
                <Form.Item name="sql_template" label="取数模板" tooltip="指标类可填参考 SQL（可选）">
                  <Input.TextArea rows={2} />
                </Form.Item>
                <Space>
                  <Button type="primary" htmlType="submit">保存</Button>
                  <Button onClick={startNew}>清空/新建</Button>
                  {selectedId && (
                    <Popconfirm title="删除此术语？" onConfirm={onDelete}>
                      <Button danger>删除</Button>
                    </Popconfirm>
                  )}
                </Space>
              </Form>
            </Card>
          </Col>
        </Row>
      </ConfigProvider>
    </PageContainer>
  )
}

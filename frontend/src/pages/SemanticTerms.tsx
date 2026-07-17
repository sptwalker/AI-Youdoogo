/** 业务术语字典（统一语义层，仅 admin）：建/改/删术语（规范名/别名/定义/类型/关联）。
 *  用途：统一跨部门口径（注入 AI 提示词）+ 别名查询扩展（喂关键词臂）。仅口径参考，不触发决议。 */
import {
  ModalForm,
  PageContainer,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components'
import { Button, Popconfirm, Space, Tag, message } from 'antd'
import { useRef } from 'react'
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

export default function SemanticTerms() {
  const actionRef = useRef<ActionType>(null)
  const reload = () => actionRef.current?.reload()

  const formFields = (
    <>
      <ProFormText name="canonical_name" label="规范名" rules={[{ required: true }]}
        tooltip="全公司统一口径的标准称呼，如「累计激活设备数」" />
      <ProFormText name="aliases" label="别名/同义词"
        tooltip="逗号或顿号分隔，如「新增设备、激活量」。查询命中别名会映射到规范名" />
      <ProFormSelect name="term_type" label="类型" initialValue="metric"
        options={TYPE_OPTIONS} rules={[{ required: true }]} />
      <ProFormTextArea name="definition" label="口径定义" tooltip="一句话说清算法/边界" />
      <ProFormText name="linked_view" label="关联数据源" tooltip="指标类可填 TD 视图名，如 v_event_4" />
      <ProFormTextArea name="sql_template" label="取数模板" tooltip="指标类可填参考 SQL（可选）" />
    </>
  )

  const columns: ProColumns<SemanticTerm>[] = [
    { title: '规范名', dataIndex: 'canonical_name', width: 160 },
    {
      title: '类型', dataIndex: 'term_type', width: 80,
      render: (_, r) => <Tag color={TYPE_COLOR[r.term_type]}>{TYPE_LABEL[r.term_type] ?? r.term_type}</Tag>,
    },
    {
      title: '别名', dataIndex: 'aliases',
      render: (_, r) => <Space size={4} wrap>{r.aliases.map((a) => <Tag key={a}>{a}</Tag>)}</Space>,
    },
    { title: '口径定义', dataIndex: 'definition', ellipsis: true },
    { title: '数据源', dataIndex: 'linked_view', width: 110 },
    {
      title: '操作', valueType: 'option', width: 110,
      render: (_, r) => [
        <ModalForm<FormVals>
          key="edit"
          title={`编辑 · ${r.canonical_name}`}
          trigger={<a>编辑</a>}
          modalProps={{ destroyOnHidden: true }}
          initialValues={{
            canonical_name: r.canonical_name, aliases: r.aliases.join('、'),
            term_type: r.term_type, definition: r.definition ?? undefined,
            linked_view: r.linked_view ?? undefined, sql_template: r.sql_template ?? undefined,
          }}
          onFinish={async (v) => {
            await updateTerm(r.id, toPayload(v))
            message.success('已保存')
            reload()
            return true
          }}
        >
          {formFields}
        </ModalForm>,
        <Popconfirm key="d" title="删除此术语？" onConfirm={async () => { await deleteTerm(r.id); message.success('已删除'); reload() }}>
          <a style={{ color: '#cf1322' }}>删除</a>
        </Popconfirm>,
      ],
    },
  ]

  return (
    <PageContainer
      title="业务术语字典"
      subTitle="统一跨部门口径：注入 AI 提示词 + 别名查询扩展。仅口径参考，不触发业务决议"
    >
      <ProTable<SemanticTerm>
        rowKey="id"
        actionRef={actionRef}
        columns={columns}
        search={false}
        options={{ reload: true, density: false, setting: false }}
        request={async () => ({ data: await listTerms(), success: true })}
        pagination={false}
        toolBarRender={() => [
          <ModalForm<FormVals>
            key="new"
            title="新建术语"
            trigger={<Button type="primary">新建术语</Button>}
            modalProps={{ destroyOnHidden: true }}
            onFinish={async (v) => {
              await createTerm(toPayload(v))
              message.success('已创建')
              reload()
              return true
            }}
          >
            {formFields}
          </ModalForm>,
        ]}
      />
    </PageContainer>
  )
}

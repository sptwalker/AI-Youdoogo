/** 系统配置（F5 密钥可 UI 填写）：按分类分栏（AI/向量/外部数据/飞书/提示词/功能）。
 *  密钥项只显示「已配置/未配置」状态、编辑时输入新值不回显旧值；非密项直接显示可改。
 *  改后即时生效（app 经 runtime_config 覆盖 .env）。 */
import {
  ModalForm,
  PageContainer,
  ProFormText,
  ProFormTextArea,
} from '@ant-design/pro-components'
import { Alert, Button, Card, List, Popconfirm, Space, Tag, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listConfigs, testConnectivity, updateConfig, type ConnResult, type SysConfig } from '../api/admin'
import { initTemplate } from '../api/org'

const CAT_LABEL: Record<string, string> = {
  llm: 'AI 大模型', embedding: '向量模型 (Embedding)', dataif: '外部数据 (ThinkingData)',
  feishu: '飞书', prompt: '提示词', feature: '功能开关',
}
const CAT_ORDER = ['llm', 'embedding', 'dataif', 'feishu', 'prompt', 'feature']

const KEY_LABEL: Record<string, string> = {
  deepseek_api_key: 'DeepSeek API Key', dashscope_api_key: '通义(Qwen/Embedding) API Key',
  zhipu_api_key: '智谱 GLM API Key', anthropic_api_key: 'Anthropic API Key',
  embedding_base_url: 'Embedding 端点', embedding_model: 'Embedding 模型',
  embedding_api_key: 'Embedding API Key',
  feishu_app_id: '飞书 App ID', feishu_app_secret: '飞书 App Secret',
  feishu_notify_enabled: '飞书通知开关（true/false）', feishu_ops_chat_id: '运营群 chat_id',
  td_base_url: 'ThinkingData 地址（http://HOST:8992）', td_api_secret: 'ThinkingData 密钥',
  td_daily_metrics_sql: 'TD 每日拉取 SQL', td_field_mapping: 'TD 字段映射（JSON）',
  agent_global_prompt: 'AI 全局红线提示词',
}

const asText = (v: unknown): string => (typeof v === 'string' ? v : JSON.stringify(v))
const label = (k: string) => KEY_LABEL[k] ?? k

function coerce(valueType: string, raw: string): unknown {
  if (valueType === 'int') return Number(raw)
  if (valueType === 'bool') return raw.trim().toLowerCase() === 'true'
  return raw
}

export default function SystemConfig() {
  const [configs, setConfigs] = useState<SysConfig[]>([])
  const [conn, setConn] = useState<ConnResult[] | null>(null)
  const [testing, setTesting] = useState(false)

  const load = () => listConfigs().then(setConfigs)
  useEffect(() => {
    void load()
  }, [])

  const runTest = async () => {
    setTesting(true)
    try {
      setConn(await testConnectivity())
    } finally {
      setTesting(false)
    }
  }
  const CONN = {
    ok: { color: 'success', text: '正常' }, fail: { color: 'error', text: '失败' },
    not_configured: { color: 'default', text: '未配置' },
  } as const

  const cats = [...new Set(configs.map((c) => c.category))].sort(
    (a, b) => (CAT_ORDER.indexOf(a) + 99) - (CAT_ORDER.indexOf(b) + 99),
  )

  const editForm = (c: SysConfig) => (
    <ModalForm<{ value: string }>
      key="e"
      title={`编辑 ${label(c.key)}`}
      trigger={<a>{c.is_secret ? '设置' : '编辑'}</a>}
      initialValues={c.is_secret ? {} : { value: asText(c.value) }}
      modalProps={{ destroyOnHidden: true }}
      onFinish={async (v) => {
        await updateConfig(c.key, coerce(c.value_type, v.value))
        message.success('已保存，即时生效')
        await load()
        return true
      }}
    >
      {c.is_secret ? (
        <ProFormText.Password name="value" label="新值（不回显旧值）" rules={[{ required: true }]}
          tooltip="密钥存于系统，读取时脱敏；请勿硬编码" />
      ) : (
        <ProFormTextArea name="value" label="值" rules={[{ required: true }]} />
      )}
    </ModalForm>
  )

  return (
    <PageContainer title="系统配置" subTitle="AI/外部数据/飞书 等配置在此填写，改后即时生效">
      <Card title="组织骨架初始化" size="small" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Alert type="info" showIcon message="按公司模板初始化/补齐组织骨架（幂等可重跑）。" />
          <Popconfirm title="确认初始化/补齐公司骨架？" onConfirm={async () => {
            const r = await initTemplate()
            message.success(`已初始化：${r.departments} 部门 / ${r.execs} 顾问 / ${r.directors} 总监助理`)
          }}>
            <Button type="primary">一键初始化 / 补齐公司骨架</Button>
          </Popconfirm>
        </Space>
      </Card>

      <Card title="AI 大模型" size="small" style={{ marginBottom: 16 }}>
        <Alert
          type="info" showIcon
          message="AI 大模型改为卡片化配置"
          description={
            <span>
              新增/管理 AI 模型（DeepSeek 等）请到 <Link to="/ai-providers">「AI 配置」</Link> 页
              按卡片填写（名称/档位/地址/Key/模型），测连通后设主用。必须建卡片，AI 才可用。
            </span>
          }
        />
      </Card>

      <Card title="连通性测试" size="small" style={{ marginBottom: 16 }}
        extra={<Button size="small" loading={testing} onClick={runTest}>测试 LLM / 飞书 / 数据平台</Button>}>
        {!conn && <Typography.Text type="secondary">填好密钥后点右上角测试外部依赖连通性（不回显密钥）。</Typography.Text>}
        <Space wrap size="middle">
          {conn?.map((c) => (
            <Tag key={c.target} color={CONN[c.status].color}>
              {c.target}：{CONN[c.status].text}
              {c.status !== 'not_configured' && ` (${c.latency_ms}ms)`}
              {c.status === 'fail' && ` — ${c.msg}`}
            </Tag>
          ))}
        </Space>
      </Card>

      {cats.map((cat) => (
        <Card key={cat} title={CAT_LABEL[cat] ?? cat} size="small" style={{ marginBottom: 16 }}>
          <List
            dataSource={configs.filter((c) => c.category === cat)}
            renderItem={(c) => (
              <List.Item actions={c.is_editable ? [editForm(c)] : []}>
                <List.Item.Meta
                  title={<Space>{label(c.key)}{c.is_secret && <Tag>密钥</Tag>}</Space>}
                  description={
                    c.is_secret ? (
                      <Tag color={c.is_set ? 'success' : 'default'}>{c.is_set ? '已配置' : '未配置'}</Tag>
                    ) : (
                      <Typography.Text style={{ whiteSpace: 'pre-wrap' }}>
                        {asText(c.value) || '（空，回退 .env）'}
                      </Typography.Text>
                    )
                  }
                />
              </List.Item>
            )}
          />
        </Card>
      ))}
    </PageContainer>
  )
}

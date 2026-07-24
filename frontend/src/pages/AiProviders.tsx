/** AI 配置（仅 admin）：BH 风格卡片化多 Provider 管理。
 *  新增卡片（名称/档位/地址/Key/模型）→ 自动测连通 → 设主用/启停/编辑/删；顶部一键检测全部。
 *  绿灯=正常 / 红灯=异常 / 灰灯=禁用或未测。密钥只显示末4位提示，不回显明文。 */
import { ModalForm, PageContainer, ProFormSelect, ProFormText } from '@ant-design/pro-components'
import { Badge, Button, Card, Col, Empty, Popconfirm, Row, Space, Tag, Tooltip, message } from 'antd'
import { useEffect, useState } from 'react'
import {
  createProvider,
  deleteProvider,
  listProviders,
  setPrimary,
  testAll,
  testProvider,
  toggleActive,
  updateProvider,
  TIER_LABEL,
  type AiProvider,
  type Tier,
} from '../api/aiProviders'

const TIER_OPTIONS = [
  { value: 'daily', label: '日常（daily）· 普通任务' },
  { value: 'reasoning', label: '推理（reasoning）· 会商/提案预研' },
]

/** 状态灯：禁用→灰，ok→绿，fail→红，未测→灰。 */
function statusBadge(p: AiProvider) {
  if (!p.is_active) return <Badge status="default" text="已禁用" />
  const map = {
    ok: <Badge status="success" text={`正常${p.last_test_latency_ms ? ` (${p.last_test_latency_ms}ms)` : ''}`} />,
    fail: <Badge status="error" text="异常" />,
    untested: <Badge status="default" text="未测试" />,
    disabled: <Badge status="default" text="已禁用" />,
  } as const
  return map[p.last_test_status] ?? map.untested
}

const cardForm = (
  <>
    <ProFormText name="name" label="名称" rules={[{ required: true }]} placeholder="如 DeepSeek 主力" />
    <ProFormSelect name="tier" label="档位" options={TIER_OPTIONS} rules={[{ required: true }]}
      tooltip="日常任务用日常档；会商/提案预研用推理档（对接 AI 员工 model_role）" />
    <ProFormText name="base_url" label="接口地址" rules={[{ required: true }]}
      placeholder="OpenAI 兼容端点，如 https://api.deepseek.com" />
    <ProFormText name="model" label="模型" rules={[{ required: true }]} placeholder="如 deepseek-chat" />
  </>
)

export default function AiProviders() {
  const [cards, setCards] = useState<AiProvider[]>([])
  const [busy, setBusy] = useState(false)

  const load = () => listProviders().then(setCards)
  useEffect(() => {
    void load()
  }, [])

  const runTest = async (id: string) => {
    const r = await testProvider(id)
    message[r.status === 'ok' ? 'success' : 'error'](`${r.status === 'ok' ? '连通正常' : '连通失败'}：${r.msg}`)
    await load()
  }

  const runTestAll = async () => {
    setBusy(true)
    try {
      const results = await testAll()
      const okN = results.filter((r) => r.status === 'ok').length
      message.success(`检测完成：${okN}/${results.length} 张正常`)
      await load()
    } finally {
      setBusy(false)
    }
  }

  const daily = cards.filter((c) => c.tier === 'daily')
  const reasoning = cards.filter((c) => c.tier === 'reasoning')

  const renderCard = (p: AiProvider) => (
    <Col key={p.id} xs={24} sm={12} lg={8} style={{ marginBottom: 16 }}>
      <Card
        size="small"
        title={
          <Space>
            {p.name}
            {p.is_primary && <Tag color="gold">主用</Tag>}
          </Space>
        }
        extra={statusBadge(p)}
        style={{ opacity: p.is_active ? 1 : 0.6, borderColor: p.is_primary ? '#faad14' : undefined }}
      >
        <div style={{ fontSize: 12, color: '#666', lineHeight: 1.9 }}>
          <div>档位：{TIER_LABEL[p.tier]}</div>
          <div>模型：{p.model}</div>
          <div style={{ wordBreak: 'break-all' }}>地址：{p.base_url}</div>
          <div>密钥：{p.api_key_set ? p.api_key_hint || '已配置' : <Tag color="warning">未配置</Tag>}</div>
          {p.last_test_status === 'fail' && p.last_test_msg && (
            <Tooltip title={p.last_test_msg}>
              <div style={{ color: '#cf1322' }}>错误：{p.last_test_msg.slice(0, 40)}…</div>
            </Tooltip>
          )}
        </div>
        <Space wrap style={{ marginTop: 12 }}>
          <a onClick={() => runTest(p.id)}>测试</a>
          {!p.is_primary && p.is_active && (
            <a onClick={async () => { await setPrimary(p.id); message.success('已设为主用'); await load() }}>设主用</a>
          )}
          <a onClick={async () => { await toggleActive(p.id, !p.is_active); await load() }}>
            {p.is_active ? '禁用' : '启用'}
          </a>
          <ModalForm
            title={`编辑 · ${p.name}`}
            trigger={<a>编辑</a>}
            modalProps={{ destroyOnHidden: true }}
            initialValues={{ name: p.name, tier: p.tier, base_url: p.base_url, model: p.model }}
            onFinish={async (v) => {
              const payload: Parameters<typeof updateProvider>[1] = {
                name: v.name, tier: v.tier as Tier, base_url: v.base_url, model: v.model,
              }
              if (v.api_key) payload.api_key = v.api_key
              await updateProvider(p.id, payload)
              message.success('已保存')
              await load()
              return true
            }}
          >
            {cardForm}
            <ProFormText.Password name="api_key" label="API Key（留空不改）"
              tooltip="留空则保留原有密钥；填写则覆盖" />
          </ModalForm>
          <Popconfirm title="删除此卡片？" onConfirm={async () => { await deleteProvider(p.id); message.success('已删除'); await load() }}>
            <a style={{ color: '#cf1322' }}>删除</a>
          </Popconfirm>
        </Space>
      </Card>
    </Col>
  )

  const section = (title: string, list: AiProvider[]) => (
    <Card title={title} size="small" style={{ marginBottom: 16 }} styles={{ body: { paddingBottom: 0 } }}>
      {list.length ? <Row gutter={16}>{list.map(renderCard)}</Row> : <Empty description="暂无卡片" />}
    </Card>
  )

  return (
    <PageContainer
      title="AI 配置"
      subTitle="卡片化多模型管理；必须建卡片 AI 才可用（不回退 .env），密钥不回显明文"
      extra={[
        <Button key="test" loading={busy} onClick={runTestAll}>检测全部</Button>,
        <ModalForm
          key="new"
          title="新增 AI 卡片"
          trigger={<Button type="primary">新增卡片</Button>}
          modalProps={{ destroyOnHidden: true }}
          initialValues={{ tier: 'daily' }}
          onFinish={async (v) => {
            const { id } = await createProvider(v as Parameters<typeof createProvider>[0])
            try {
              const r = await testProvider(id)
              message[r.status === 'ok' ? 'success' : 'warning'](
                r.status === 'ok' ? '已创建并连通正常' : `已创建，但连通失败：${r.msg}`,
              )
            } catch {
              message.warning('卡片已创建，但自动连通测试未完成，可稍后手动测试')
            }
            await load()
            return true
          }}
        >
          {cardForm}
          <ProFormText.Password name="api_key" label="API Key" rules={[{ required: true }]}
            tooltip="密钥存于系统，读取时脱敏；请勿硬编码" />
        </ModalForm>,
      ]}
    >
      {section(`日常档（${daily.length}）`, daily)}
      {section(`推理档（${reasoning.length}）`, reasoning)}
    </PageContainer>
  )
}

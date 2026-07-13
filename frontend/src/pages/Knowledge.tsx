/** 知识库：问答（带来源溯源）+ 文档管理（上传/粘贴/飞书入库/删除）。 */
import {
  ModalForm,
  PageContainer,
  ProFormText,
  ProFormTextArea,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components'
import { Button, Card, Input, List, Popconfirm, Space, Spin, Tag, Typography, Upload, message } from 'antd'
import { useRef, useState } from 'react'
import {
  askKnowledge,
  deleteKnowledgeFile,
  ingestFeishu,
  ingestText,
  listKnowledgeFiles,
  uploadKnowledgeFile,
  type AskResponse,
  type KnowledgeFile,
} from '../api/knowledge'

const STATUS_TAG: Record<KnowledgeFile['status'], { color: string; text: string }> = {
  uploaded: { color: 'default', text: '待处理' },
  parsing: { color: 'processing', text: '解析中' },
  indexed: { color: 'success', text: '已入库' },
  failed: { color: 'error', text: '失败' },
}

export default function Knowledge() {
  const actionRef = useRef<ActionType>(null)
  const [query, setQuery] = useState('')
  const [asking, setAsking] = useState(false)
  const [answer, setAnswer] = useState<AskResponse | null>(null)

  const ask = async () => {
    if (!query.trim()) return
    setAsking(true)
    try {
      setAnswer(await askKnowledge(query))
    } catch {
      /* 错误已由拦截器提示 */
    } finally {
      setAsking(false)
    }
  }

  const columns: ProColumns<KnowledgeFile>[] = [
    { title: '文件名', dataIndex: 'file_name' },
    { title: '分类', dataIndex: 'category', render: (_, r) => r.category || '-' },
    {
      title: '状态',
      dataIndex: 'status',
      render: (_, r) => <Tag color={STATUS_TAG[r.status].color}>{STATUS_TAG[r.status].text}</Tag>,
    },
    { title: '上传时间', dataIndex: 'create_time', valueType: 'dateTime' },
    {
      title: '操作',
      valueType: 'option',
      render: (_, r) => [
        <Popconfirm
          key="del"
          title="确认删除该文档及其向量？"
          onConfirm={async () => {
            await deleteKnowledgeFile(r.id)
            message.success('已删除')
            actionRef.current?.reload()
          }}
        >
          <a>删除</a>
        </Popconfirm>,
      ],
    },
  ]

  return (
    <PageContainer title="知识库">
      <Card title="知识库问答" style={{ marginBottom: 16 }}>
        <Space.Compact style={{ width: '100%' }}>
          <Input
            placeholder="就公司文档提问，答案将标注来源编号"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onPressEnter={ask}
          />
          <Button type="primary" onClick={ask} loading={asking}>
            提问
          </Button>
        </Space.Compact>
        {asking && <Spin style={{ marginTop: 16 }} />}
        {answer && !asking && (
          <div style={{ marginTop: 16 }}>
            <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
              {answer.answer}
            </Typography.Paragraph>
            {answer.sources.length > 0 && (
              <List
                size="small"
                header={<b>来源</b>}
                dataSource={answer.sources}
                renderItem={(s) => (
                  <List.Item>
                    [{s.index}] {s.file_name} · 片段 #{s.chunk_index}
                  </List.Item>
                )}
              />
            )}
          </div>
        )}
      </Card>

      <ProTable<KnowledgeFile>
        rowKey="id"
        actionRef={actionRef}
        search={false}
        columns={columns}
        request={async () => ({ data: await listKnowledgeFiles(), success: true })}
        toolBarRender={() => [
          <Upload
            key="upload"
            accept=".txt,.md,.markdown,.docx,.pdf"
            showUploadList={false}
            beforeUpload={(file) => {
              uploadKnowledgeFile(file)
                .then(() => {
                  message.success('已上传并入库')
                  actionRef.current?.reload()
                })
                .catch(() => {
                  /* 错误已由拦截器提示 */
                })
              return false
            }}
          >
            <Button>上传文档 (txt/md/docx/pdf)</Button>
          </Upload>,
          <ModalForm<{ title: string; text: string; category?: string }>
            key="text"
            title="粘贴正文入库"
            trigger={<Button>粘贴入库</Button>}
            modalProps={{ destroyOnHidden: true }}
            onFinish={async (v) => {
              await ingestText(v)
              message.success('已入库')
              actionRef.current?.reload()
              return true
            }}
          >
            <ProFormText name="title" label="标题" rules={[{ required: true }]} />
            <ProFormTextArea name="text" label="正文" rules={[{ required: true }]} />
            <ProFormText name="category" label="分类" />
          </ModalForm>,
          <ModalForm<{ document_id: string; category?: string }>
            key="feishu"
            title="飞书云文档入库"
            trigger={<Button>飞书文档</Button>}
            modalProps={{ destroyOnHidden: true }}
            onFinish={async (v) => {
              await ingestFeishu(v)
              message.success('已入库')
              actionRef.current?.reload()
              return true
            }}
          >
            <ProFormText name="document_id" label="文档 ID" rules={[{ required: true }]} />
            <ProFormText name="category" label="分类" />
          </ModalForm>,
        ]}
      />
    </PageContainer>
  )
}

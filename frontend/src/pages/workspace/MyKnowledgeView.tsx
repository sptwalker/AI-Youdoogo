/** 我的知识（B1.4）：入库粘贴正文 / 列出本人条目 / 带来源问答。
 *
 *  隔离：所有请求走 /my-knowledge/*，owner 恒为登录用户，仅本人个人库参与 → 跨人不可见。
 *  红线：问答为顾问型产出（只读 + 溯源），不外发、不改业务。 */
import { Button, Card, Empty, Input, List, Space, Tag, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import type { KnowledgeFile } from '../../api/knowledge'
import {
  askMyKnowledge,
  ingestMyText,
  listMyDocuments,
} from '../../api/myKnowledge'
import type { AskResponse } from '../../api/knowledge'
import Markdown from '../../components/Markdown'

export default function MyKnowledgeView() {
  const [docs, setDocs] = useState<KnowledgeFile[]>([])
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)
  const [query, setQuery] = useState('')
  const [asking, setAsking] = useState(false)
  const [answer, setAnswer] = useState<AskResponse | null>(null)

  const reload = () => {
    void listMyDocuments().then(setDocs).catch(() => undefined)
  }
  useEffect(reload, [])

  const onSave = async () => {
    setSaving(true)
    try {
      await ingestMyText({ title: title.trim(), text: text.trim() })
      message.success('已存入我的知识')
      setTitle('')
      setText('')
      reload()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '存入失败')
    } finally {
      setSaving(false)
    }
  }

  const onAsk = async () => {
    setAsking(true)
    setAnswer(null)
    try {
      setAnswer(await askMyKnowledge(query.trim()))
    } catch (error) {
      message.error(error instanceof Error ? error.message : '提问失败')
    } finally {
      setAsking(false)
    }
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card size="small" title="向我的知识提问（答案带来源，仅本人条目参与）">
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Input.Search
            placeholder="例如：上季度复盘里我总结了哪些改进点？"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            enterButton="提问"
            loading={asking}
            onSearch={() => query.trim().length >= 2 && void onAsk()}
          />
          {answer && (
            <Card size="small" type="inner" title="回答">
              <Markdown>{answer.answer}</Markdown>
              {answer.sources.length > 0 && (
                <div style={{ marginTop: 8 }}>
                  <Typography.Text type="secondary">来源：</Typography.Text>
                  {answer.sources.map((s) => (
                    <Tag key={`${s.file_id}-${s.chunk_index}`} title={s.snippet}>
                      [{s.index}] {s.file_name}
                    </Tag>
                  ))}
                </div>
              )}
            </Card>
          )}
        </Space>
      </Card>

      <Card size="small" title="存入一条知识（粘贴正文）">
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Input placeholder="标题" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} />
          <Input.TextArea
            placeholder="粘贴要沉淀的正文……"
            value={text}
            onChange={(e) => setText(e.target.value)}
            autoSize={{ minRows: 3, maxRows: 10 }}
            maxLength={20000}
          />
          <Button
            type="primary"
            loading={saving}
            disabled={title.trim().length === 0 || text.trim().length === 0}
            onClick={() => void onSave()}
          >
            存入
          </Button>
        </Space>
      </Card>

      <Card size="small" title={`我的知识条目（${docs.length}）`}>
        {docs.length === 0 ? (
          <Empty description="还没有个人知识，先存入或让 AI 产出自动沉淀" />
        ) : (
          <List
            size="small"
            dataSource={docs}
            renderItem={(doc) => (
              <List.Item>
                <Space size={6} wrap>
                  <span>{doc.file_name}</span>
                  {doc.category && <Tag>{doc.category}</Tag>}
                  <Typography.Text type="secondary">{doc.status}</Typography.Text>
                </Space>
              </List.Item>
            )}
          />
        )}
      </Card>
    </Space>
  )
}

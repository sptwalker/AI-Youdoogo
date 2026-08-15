/** 相关知识推荐（B1.5）：按检索词拉本人知识 Top5，只读旁栏；不自动改任务。
 *
 *  红线：纯只读推荐，命中仅供参考，真人自行取用。检索走 /my-knowledge/search（仅本人库）。 */
import { List, Spin, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { searchMyKnowledge, type SearchHit } from '../api/myKnowledge'
import { buildSuggestQuery } from '../features/knowledge/suggest'

export default function MyKnowledgeSuggest({
  title,
  description,
  topK = 5,
}: {
  title?: string | null
  description?: string | null
  topK?: number
}) {
  const [hits, setHits] = useState<SearchHit[]>([])
  const [loading, setLoading] = useState(false)
  const query = buildSuggestQuery(title, description)

  useEffect(() => {
    if (query === null) {
      setHits([])
      return
    }
    let cancelled = false
    setLoading(true)
    // 输入抖动 → 防抖 400ms 再检索，避免每键一请求。
    const timer = setTimeout(() => {
      void searchMyKnowledge(query, topK)
        .then((r) => {
          if (!cancelled) setHits(r.hits)
        })
        .catch(() => {
          if (!cancelled) setHits([])
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
    }, 400)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [query, topK])

  if (query === null) return null
  return (
    <div style={{ marginTop: 8 }}>
      <Typography.Text type="secondary">相关知识（本人 · 只读参考）</Typography.Text>
      <Spin spinning={loading} size="small">
        <List
          size="small"
          locale={{ emptyText: '暂无相关知识' }}
          dataSource={hits}
          renderItem={(hit) => (
            <List.Item>
              <Typography.Text ellipsis={{ tooltip: hit.snippet }}>
                {hit.file_name}：{hit.snippet}
              </Typography.Text>
            </List.Item>
          )}
        />
      </Spin>
    </div>
  )
}

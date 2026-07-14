/** 统一的 Markdown 渲染组件（用于所有 AI 输出/富文本内容）。
 *  react-markdown 默认转义原始 HTML，无 XSS 风险；remark-gfm 支持表格/删除线/任务列表等。 */
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export default function Markdown({ children }: { children?: string | null }) {
  return (
    <div className="md-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children ?? ''}</ReactMarkdown>
    </div>
  )
}

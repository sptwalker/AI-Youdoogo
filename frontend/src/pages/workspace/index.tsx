/** 工作台外壳：看板 / 列表 / 收件箱三视图切换（阶段 A 外壳，时间线/日历延后到 B）。 */
import { PageContainer } from '@ant-design/pro-components'
import { Segmented } from 'antd'
import { useState } from 'react'
import AiTaskView from './AiTaskView'
import BoardView from './BoardView'
import CalendarView from './CalendarView'
import InboxView from './InboxView'
import ListView from './ListView'
import MyKnowledgeView from './MyKnowledgeView'
import TimelineView from './TimelineView'

type View = '看板' | '列表' | '收件箱' | '时间线' | '日历' | 'AI 任务' | '我的知识'

export default function Workspace() {
  const [view, setView] = useState<View>('看板')
  return (
    <PageContainer
      title="工作台"
      content={<Segmented<View> options={['看板', '列表', '收件箱', '时间线', '日历', 'AI 任务', '我的知识']} value={view} onChange={setView} />}
    >
      {view === '看板' && <BoardView />}
      {view === '列表' && <ListView />}
      {view === '收件箱' && <InboxView />}
      {view === '时间线' && <TimelineView />}
      {view === '日历' && <CalendarView />}
      {view === 'AI 任务' && <AiTaskView />}
      {view === '我的知识' && <MyKnowledgeView />}
    </PageContainer>
  )
}

import { PageContainer } from '@ant-design/pro-components'
import DiscussionWorkspace from '../features/discussion/DiscussionWorkspace'

export default function Discussion() {
  return (
    <PageContainer title="协作空间" subTitle="人机讨论 · @顾问触发参考意见 · 讨论升格为提案/任务">
      <DiscussionWorkspace />
    </PageContainer>
  )
}

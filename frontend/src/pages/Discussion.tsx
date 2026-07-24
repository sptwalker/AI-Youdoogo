import { PageContainer } from '@ant-design/pro-components'
import { useOutletContext } from 'react-router-dom'
import type { UserInfo } from '../api/auth'
import DiscussionWorkspace from '../features/discussion/DiscussionWorkspace'
import { hasManagerRole } from './managementPermissions'

export default function Discussion() {
  const { me } = useOutletContext<{ me: UserInfo | null }>()
  const canPromote = hasManagerRole(me?.role_code)
  return (
    <PageContainer title="协作空间" subTitle="人机讨论 · @顾问触发参考意见 · 讨论升格为提案/任务">
      <DiscussionWorkspace canPromote={canPromote} />
    </PageContainer>
  )
}

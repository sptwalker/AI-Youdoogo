import { ModalForm, PageContainer, ProFormText, ProTable, type ActionType, type ProColumns } from '@ant-design/pro-components'
import { AutoComplete, Button, Card, Drawer, Input, List, Popconfirm, Space, Tag, message } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import type { UserInfo } from '../api/auth'
import {
  aiSpeak, aiVote, confirmResolution, convertResolution, createMeeting, createResolution, discuss,
  generateMinutes, getMeeting, getTally, listMeetings, listVoteSubjects, MEETING_STATUS,
  setMeetingStatus, vote, type Discuss, type Meeting, type MeetingDetail, type Tally,
} from '../api/meetings'
import Markdown from '../components/Markdown'
import { usePendingActions } from '../hooks/usePendingActions'
import { hasManagerRole } from './managementPermissions'

const STATUS_COLOR: Record<string, string> = { scheduled: 'default', in_progress: 'processing', closed: 'success' }

export default function Meetings() {
  const { me } = useOutletContext<{ me: UserInfo | null }>()
  const actionRef = useRef<ActionType>(null)
  const openRequestRef = useRef(0)
  const aiSpeakControllerRef = useRef<AbortController | null>(null)
  const tallyRequestRef = useRef(0)
  const [detail, setDetail] = useState<MeetingDetail | null>(null)
  const [subject, setSubject] = useState('')
  const [speech, setSpeech] = useState('')
  const [aiTopic, setAiTopic] = useState('')
  const [resolutionText, setResolutionText] = useState('')
  const [tally, setTally] = useState<Tally | null>(null)
  const [subjects, setSubjects] = useState<string[]>([])
  const [aiSpeaking, setAiSpeaking] = useState(false)
  const pending = usePendingActions()
  const canManage = hasManagerRole(me?.role_code)
  const meetingId = detail?.meeting.id
  const inProgress = detail?.meeting.status === 'in_progress'

  useEffect(() => {
    aiSpeakControllerRef.current?.abort()
    aiSpeakControllerRef.current = null
    tallyRequestRef.current += 1
    setSubject('')
    setSpeech('')
    setAiTopic('')
    setResolutionText('')
    setTally(null)
    setSubjects([])
    setAiSpeaking(false)
    if (!meetingId) return
    let active = true
    void listVoteSubjects(meetingId).then((items) => { if (active) setSubjects(items) }).catch(() => {})
    return () => {
      active = false
      aiSpeakControllerRef.current?.abort()
    }
  }, [meetingId])

  const refresh = async () => {
    if (!meetingId) return
    const next = await getMeeting(meetingId)
    setDetail((current) => current?.meeting.id === meetingId ? next : current)
  }
  const showTally = async (nextSubject: string) => {
    if (!meetingId || !nextSubject) return
    const requestId = ++tallyRequestRef.current
    const next = await getTally(meetingId, nextSubject)
    if (requestId !== tallyRequestRef.current) return
    setTally(next)
    setSubjects((current) => current.includes(nextSubject) ? current : [...current, nextSubject])
  }
  const sendHumanSpeech = () => {
    const content = speech.trim()
    if (!meetingId || !content) return
    void pending.run(`meeting:${meetingId}:discuss`, async () => {
      await discuss(meetingId, content)
      setSpeech('')
      await refresh()
    }).catch(() => {})
  }
  const sendAiSpeech = async () => {
    const topic = aiTopic.trim()
    if (!meetingId || !topic || aiSpeakControllerRef.current) return
    const controller = new AbortController()
    const streamId = `__streaming__-${meetingId}`
    aiSpeakControllerRef.current = controller
    setAiSpeaking(true)
    try {
      await aiSpeak(meetingId, topic, (event, data) => {
        if (event === 'message_start') {
          const start = data as unknown as { speaker_name: string }
          setDetail((current) => current && ({ ...current, discussions: [...current.discussions, { id: streamId, speaker_type: 'ai', speaker_name: start.speaker_name, content: '', create_time: '' }] }))
        } else if (event === 'delta') {
          const text = String((data as { text?: unknown }).text ?? '')
          setDetail((current) => current && ({ ...current, discussions: current.discussions.map((item) => item.id === streamId ? { ...item, content: item.content + text } : item) }))
        } else if (event === 'message_end') {
          const persistedMessage = data as unknown as Discuss
          setDetail((current) => current && ({ ...current, discussions: current.discussions.map((item) => item.id === streamId ? persistedMessage : item) }))
        }
      }, { signal: controller.signal })
      setAiTopic('')
    } catch {
      setDetail((current) => current && ({ ...current, discussions: current.discussions.filter((item) => item.id !== streamId) }))
    } finally {
      if (aiSpeakControllerRef.current === controller) {
        aiSpeakControllerRef.current = null
        setAiSpeaking(false)
      }
    }
  }
  const castVote = (choice: 'approve' | 'reject' | 'ai') => {
    const value = subject.trim()
    if (!meetingId || !value) return
    setSubject(value)
    const key = `meeting:${meetingId}:${choice === 'ai' ? 'ai-vote' : `vote:${choice}`}`
    void pending.run(key, async () => {
      if (choice === 'ai') await aiVote(meetingId, value)
      else await vote(meetingId, value, choice)
      await showTally(value)
    }).catch(() => {})
  }
  const columns: ProColumns<Meeting>[] = [
    { title: '主题', dataIndex: 'title' },
    { title: '状态', dataIndex: 'status', render: (_, meeting) => <Tag color={STATUS_COLOR[meeting.status] ?? 'default'}>{MEETING_STATUS[meeting.status] ?? meeting.status}</Tag> },
    { title: '创建时间', dataIndex: 'create_time', valueType: 'dateTime' },
    { title: '操作', valueType: 'option', render: (_, meeting) => [<a key="open" onClick={() => {
      const requestId = ++openRequestRef.current
      void getMeeting(meeting.id).then((next) => { if (requestId === openRequestRef.current) setDetail(next) })
    }}>进入</a>] },
  ]

  return <PageContainer title="会议会商">
    <ProTable<Meeting>
      rowKey="id" actionRef={actionRef} search={false} columns={columns}
      request={async () => ({ data: await listMeetings(), success: true })}
      toolBarRender={() => canManage ? [<ModalForm key="new" title="新建会议" width={420} trigger={<Button type="primary">新建会议</Button>} modalProps={{ destroyOnClose: true }} onFinish={async (values: { title: string }) => {
        await createMeeting(values.title.trim())
        message.success('已创建')
        actionRef.current?.reload()
        return true
      }}><ProFormText name="title" label="会议主题" placeholder="请输入会议主题" rules={[{ required: true, message: '请输入会议主题' }, { max: 100, message: '主题不超过 100 字' }]} /></ModalForm>] : []}
    />
    <Drawer open={Boolean(detail)} onClose={() => { openRequestRef.current += 1; setDetail(null) }} width="min(640px, 100vw)" title={detail && `${detail.meeting.title}（${MEETING_STATUS[detail.meeting.status] ?? detail.meeting.status}）`}>
      {detail && <Space direction="vertical" style={{ width: '100%' }} size="middle">
        {canManage && <Space>
          {detail.meeting.status === 'scheduled' && <Button type="primary" loading={pending.isPending(`meeting:${detail.meeting.id}:start`)} onClick={() => void pending.run(`meeting:${detail.meeting.id}:start`, async () => { await setMeetingStatus(detail.meeting.id, 'in_progress'); message.success('会议开始'); await refresh() }).catch(() => {})}>开始会议</Button>}
          {inProgress && <Popconfirm title="确认结束会议?" description="结束后不可再发言、投票或生成纪要,且无法重新开启。" okText="结束会议" okButtonProps={{ danger: true }} cancelText="取消" onConfirm={() => void pending.run(`meeting:${detail.meeting.id}:close`, async () => { await setMeetingStatus(detail.meeting.id, 'closed'); message.success('会议结束'); await refresh() }).catch(() => {})}><Button danger loading={pending.isPending(`meeting:${detail.meeting.id}:close`)}>结束会议</Button></Popconfirm>}
        </Space>}
        <Card size="small" title="发言">
          <List size="small" dataSource={detail.discussions} locale={{ emptyText: '暂无发言' }} renderItem={(discussion) => <List.Item><Tag color={discussion.speaker_type === 'ai' ? 'blue' : 'default'}>{discussion.speaker_name}</Tag><Markdown>{discussion.content}</Markdown></List.Item>} />
          {inProgress && <Space direction="vertical" style={{ width: '100%', marginTop: 8 }} size={8}>
            <Space.Compact style={{ width: '100%' }}><Input placeholder="真人发言…" value={speech} onChange={(event) => setSpeech(event.target.value)} onPressEnter={sendHumanSpeech} /><Button loading={pending.isPending(`meeting:${detail.meeting.id}:discuss`)} onClick={sendHumanSpeech}>发言</Button></Space.Compact>
            {canManage && <Space.Compact style={{ width: '100%' }}><Input placeholder="输入议题,让 AI 专家发言" value={aiTopic} onChange={(event) => setAiTopic(event.target.value)} disabled={aiSpeaking} /><Button type="primary" loading={aiSpeaking} onClick={() => void sendAiSpeech()}>AI专家</Button></Space.Compact>}
          </Space>}
        </Card>
        {inProgress && <Card size="small" title="投票（真人票决定，AI票仅参考)">
          <Space.Compact style={{ width: '100%' }}>
            <AutoComplete style={{ width: '100%' }} placeholder="表决对象（可选已有或新建）" value={subject} onChange={setSubject} options={subjects.map((item) => ({ value: item }))} filterOption={(input, option) => (option?.value ?? '').toLowerCase().includes(input.toLowerCase())} />
            <Button loading={pending.isPending(`meeting:${detail.meeting.id}:vote:approve`)} onClick={() => castVote('approve')}>赞成</Button><Button danger loading={pending.isPending(`meeting:${detail.meeting.id}:vote:reject`)} onClick={() => castVote('reject')}>反对</Button>
            {canManage && <Button type="primary" loading={pending.isPending(`meeting:${detail.meeting.id}:ai-vote`)} onClick={() => castVote('ai')}>AI参考票</Button>}
            <Button onClick={() => { const value = subject.trim(); if (value) { setSubject(value); void showTally(value) } }}>统计</Button>
          </Space.Compact>
          {tally && tally.subject === subject && <div style={{ marginTop: 8 }}><Tag color={tally.human_passed ? 'success' : 'default'}>真人票{tally.human_passed ? '通过' : '未过'}</Tag><span>真人 赞成 {tally.human.approve ?? 0} · 反对 {tally.human.reject ?? 0} · AI参考 赞成 {tally.ai.approve ?? 0} · 反对 {tally.ai.reject ?? 0}</span></div>}
        </Card>}
        <Card size="small" title="会议纪要" extra={canManage ? <Button size="small" disabled={detail.discussions.length === 0} loading={pending.isPending(`meeting:${detail.meeting.id}:minutes`)} onClick={() => void pending.run(`meeting:${detail.meeting.id}:minutes`, async () => {
          const key = `meeting:${detail.meeting.id}:minutes`
          message.loading({ content: '生成中…', key, duration: 0 })
          try { await generateMinutes(detail.meeting.id); message.success({ content: '已生成', key }); await refresh() } catch (error) { message.destroy(key); throw error }
        }).catch(() => {})}>生成纪要</Button> : undefined}><Markdown>{detail.meeting.summary || '（暂无纪要）'}</Markdown></Card>
        <Card size="small" title="决议（须真人确认生效）">
          <List size="small" dataSource={detail.resolutions} locale={{ emptyText: '暂无决议' }} renderItem={(resolution) => {
            const action = resolution.is_confirmed
              ? (resolution.converted_task_id ? <Tag color="success" key="task">已转任务卡</Tag> : <Button key="convert" type="link" size="small" loading={pending.isPending(`resolution:${resolution.id}:convert`)} onClick={() => void pending.run(`resolution:${resolution.id}:convert`, async () => { await convertResolution(resolution.id); message.success('已转任务卡'); await refresh() }).catch(() => {})}>转任务卡</Button>)
              : <Button key="confirm" type="link" size="small" loading={pending.isPending(`resolution:${resolution.id}:confirm`)} onClick={() => void pending.run(`resolution:${resolution.id}:confirm`, async () => { await confirmResolution(resolution.id); message.success('已确认生效'); await refresh() }).catch(() => {})}>确认生效</Button>
            return <List.Item actions={canManage ? [action] : []}><Tag color={resolution.is_confirmed ? 'green' : 'orange'}>{resolution.is_confirmed ? '已确认' : '待确认'}</Tag><Markdown>{resolution.content}</Markdown></List.Item>
          }} />
          {canManage && <Space.Compact style={{ width: '100%', marginTop: 8 }}><Input placeholder="登记决议内容" value={resolutionText} onChange={(event) => setResolutionText(event.target.value)} /><Button loading={pending.isPending(`meeting:${detail.meeting.id}:resolution`)} onClick={() => {
            const content = resolutionText.trim()
            if (!content) return
            void pending.run(`meeting:${detail.meeting.id}:resolution`, async () => { await createResolution(detail.meeting.id, content); setResolutionText(''); await refresh() }).catch(() => {})
          }}>登记决议</Button></Space.Compact>}
        </Card>
      </Space>}
    </Drawer>
  </PageContainer>
}

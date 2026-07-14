/** 会议：列表 + 详情抽屉（开始/结束、发言、AI专家、投票、纪要、决议→确认→转任务卡）。 */
import { PageContainer, ProTable, type ActionType, type ProColumns } from '@ant-design/pro-components'
import { Button, Card, Drawer, Input, List, Space, Tag, message } from 'antd'
import { useRef, useState } from 'react'
import Markdown from '../components/Markdown'
import {
  aiSpeak,
  aiVote,
  confirmResolution,
  convertResolution,
  createMeeting,
  createResolution,
  discuss,
  generateMinutes,
  getMeeting,
  getTally,
  listMeetings,
  MEETING_STATUS,
  setMeetingStatus,
  vote,
  type Discuss,
  type Meeting,
  type Resolution,
  type Tally,
} from '../api/meetings'

const STATUS_COLOR: Record<string, string> = {
  scheduled: 'default',
  in_progress: 'processing',
  closed: 'success',
}

interface Detail {
  meeting: Meeting
  discussions: Discuss[]
  resolutions: Resolution[]
}

export default function Meetings() {
  const actionRef = useRef<ActionType>(null)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [subject, setSubject] = useState('')
  const [speech, setSpeech] = useState('')
  const [resText, setResText] = useState('')
  const [tally, setTally] = useState<Tally | null>(null)

  const open = async (id: string) => setDetail(await getMeeting(id))
  const refresh = async () => detail && setDetail(await getMeeting(detail.meeting.id))
  const inProgress = detail?.meeting.status === 'in_progress'

  const showTally = async (mid: string, subj: string) => {
    if (subj) setTally(await getTally(mid, subj))
  }

  const columns: ProColumns<Meeting>[] = [
    { title: '主题', dataIndex: 'title' },
    {
      title: '状态',
      dataIndex: 'status',
      render: (_, r) => <Tag color={STATUS_COLOR[r.status]}>{MEETING_STATUS[r.status]}</Tag>,
    },
    { title: '创建时间', dataIndex: 'create_time', valueType: 'dateTime' },
    { title: '操作', valueType: 'option', render: (_, r) => [<a key="o" onClick={() => open(r.id)}>进入</a>] },
  ]

  return (
    <PageContainer title="会议会商">
      <ProTable<Meeting>
        rowKey="id"
        actionRef={actionRef}
        search={false}
        columns={columns}
        request={async () => ({ data: await listMeetings(), success: true })}
        toolBarRender={() => [
          <Button key="new" type="primary" onClick={async () => {
            const t = prompt('会议主题')
            if (t) { await createMeeting(t); message.success('已创建'); actionRef.current?.reload() }
          }}>新建会议</Button>,
        ]}
      />

      <Drawer open={!!detail} onClose={() => setDetail(null)} width={640}
        title={detail && `${detail.meeting.title}（${MEETING_STATUS[detail.meeting.status]}）`}>
        {detail && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Space>
              {detail.meeting.status === 'scheduled' && (
                <Button type="primary" onClick={async () => {
                  await setMeetingStatus(detail.meeting.id, 'in_progress'); message.success('会议开始'); refresh()
                }}>开始会议</Button>
              )}
              {inProgress && (
                <Button onClick={async () => {
                  await setMeetingStatus(detail.meeting.id, 'closed'); message.success('会议结束'); refresh()
                }}>结束会议</Button>
              )}
            </Space>

            <Card size="small" title="发言">
              <List size="small" dataSource={detail.discussions} locale={{ emptyText: '暂无发言' }}
                renderItem={(d) => (
                  <List.Item>
                    <Tag color={d.speaker_type === 'ai' ? 'blue' : 'default'}>{d.speaker_name}</Tag>
                    <Markdown>{d.content}</Markdown>
                  </List.Item>
                )} />
              {inProgress && (
                <Space.Compact style={{ width: '100%', marginTop: 8 }}>
                  <Input placeholder="真人发言 / 或输入议题给AI专家" value={speech}
                    onChange={(e) => setSpeech(e.target.value)} />
                  <Button onClick={async () => {
                    if (!speech.trim()) return
                    await discuss(detail.meeting.id, speech); setSpeech(''); refresh()
                  }}>发言</Button>
                  <Button type="primary" onClick={async () => {
                    if (!speech.trim()) return
                    const streamId = '__streaming__'
                    try {
                      await aiSpeak(detail.meeting.id, speech, (event, data) => {
                        if (event === 'message_start') {
                          const d = data as unknown as { speaker_name: string }
                          setDetail((prev) => prev && ({ ...prev, discussions: [...prev.discussions, { id: streamId, speaker_type: 'ai', speaker_name: d.speaker_name, content: '', create_time: '' }] }))
                        } else if (event === 'delta') {
                          const t = String((data as { text?: unknown }).text ?? '')
                          setDetail((prev) => prev && ({ ...prev, discussions: prev.discussions.map((x) => (x.id === streamId ? { ...x, content: x.content + t } : x)) }))
                        } else if (event === 'message_end') {
                          const msg = data as unknown as Discuss
                          setDetail((prev) => prev && ({ ...prev, discussions: prev.discussions.map((x) => (x.id === streamId ? msg : x)) }))
                        }
                      })
                      setSpeech('')
                    } catch {
                      setDetail((prev) => prev && ({ ...prev, discussions: prev.discussions.filter((x) => x.id !== streamId) }))
                    }
                  }}>AI专家</Button>
                </Space.Compact>
              )}
            </Card>

            {inProgress && (
              <Card size="small" title="投票（真人票决定，AI票仅参考）">
                <Space.Compact style={{ width: '100%' }}>
                  <Input placeholder="表决对象" value={subject} onChange={(e) => setSubject(e.target.value)} />
                  <Button onClick={async () => { if (subject) { await vote(detail.meeting.id, subject, 'approve'); await showTally(detail.meeting.id, subject) } }}>赞成</Button>
                  <Button danger onClick={async () => { if (subject) { await vote(detail.meeting.id, subject, 'reject'); await showTally(detail.meeting.id, subject) } }}>反对</Button>
                  <Button type="primary" onClick={async () => { if (subject) { await aiVote(detail.meeting.id, subject); await showTally(detail.meeting.id, subject) } }}>AI参考票</Button>
                  <Button onClick={() => showTally(detail.meeting.id, subject)}>统计</Button>
                </Space.Compact>
                {tally && tally.subject === subject && (
                  <div style={{ marginTop: 8 }}>
                    <Tag color={tally.human_passed ? 'success' : 'default'}>
                      真人票{tally.human_passed ? '通过' : '未过'}
                    </Tag>
                    <span>真人 {JSON.stringify(tally.human)} · AI参考 {JSON.stringify(tally.ai)}</span>
                  </div>
                )}
              </Card>
            )}

            <Card size="small" title="会议纪要"
              extra={<Button size="small" onClick={async () => {
                message.loading({ content: '生成中…', key: 'm' })
                await generateMinutes(detail.meeting.id); message.success({ content: '已生成', key: 'm' }); refresh()
              }}>生成纪要</Button>}>
              <Markdown>{detail.meeting.summary || '（暂无纪要）'}</Markdown>
            </Card>

            <Card size="small" title="决议（须真人确认生效）">
              <List size="small" dataSource={detail.resolutions} locale={{ emptyText: '暂无决议' }}
                renderItem={(r) => (
                  <List.Item actions={[
                    r.is_confirmed
                      ? (r.converted_task_id
                          ? <Tag color="success" key="t">已转任务卡</Tag>
                          : <a key="cv" onClick={async () => { await convertResolution(r.id); message.success('已转任务卡'); refresh() }}>转任务卡</a>)
                      : <a key="cf" onClick={async () => { await confirmResolution(r.id); message.success('已确认生效'); refresh() }}>确认生效</a>,
                  ]}>
                    <Tag color={r.is_confirmed ? 'green' : 'orange'}>{r.is_confirmed ? '已确认' : '待确认'}</Tag>
                    <Markdown>{r.content}</Markdown>
                  </List.Item>
                )} />
              <Space.Compact style={{ width: '100%', marginTop: 8 }}>
                <Input placeholder="登记决议内容" value={resText} onChange={(e) => setResText(e.target.value)} />
                <Button onClick={async () => {
                  if (!resText.trim()) return
                  await createResolution(detail.meeting.id, resText); setResText(''); refresh()
                }}>登记决议</Button>
              </Space.Compact>
            </Card>
          </Space>
        )}
      </Drawer>
    </PageContainer>
  )
}

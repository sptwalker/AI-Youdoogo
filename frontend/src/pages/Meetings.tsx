/** 会议：列表 + 详情抽屉（开始/结束、发言、AI专家、投票、纪要、决议→确认→转任务卡）。 */
import { ModalForm, PageContainer, ProFormText, ProTable, type ActionType, type ProColumns } from '@ant-design/pro-components'
import { AutoComplete, Button, Card, Drawer, Input, List, Popconfirm, Space, Tag, message } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import type { UserInfo } from '../api/auth'
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
  listVoteSubjects,
  MEETING_STATUS,
  setMeetingStatus,
  vote,
  type Discuss,
  type Meeting,
  type Resolution,
  type Tally,
} from '../api/meetings'
import { hasManagerRole } from './managementPermissions'
import { usePendingActions } from '../hooks/usePendingActions'

const STATUS_COLOR: Record<string, string> = {
  scheduled: 'default',
  in_progress: 'processing',
  closed: 'success',
}

/** 把 {approve:2, reject:1} 这样的原始票数渲染成「赞成 2 · 反对 1」。 */
function formatVotes(counts: Record<string, number>): string {
  return `赞成 ${counts.approve ?? 0} · 反对 ${counts.reject ?? 0}`
}

interface Detail {
  meeting: Meeting
  discussions: Discuss[]
  resolutions: Resolution[]
}

export default function Meetings() {
  const { me } = useOutletContext<{ me: UserInfo | null }>()
  const actionRef = useRef<ActionType>(null)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [subject, setSubject] = useState('')
  const [speech, setSpeech] = useState('')
  const [aiTopic, setAiTopic] = useState('')
  const [resText, setResText] = useState('')
  const [tally, setTally] = useState<Tally | null>(null)
  const [subjects, setSubjects] = useState<string[]>([])
  const [aiSpeaking, setAiSpeaking] = useState(false)
  const openRequestRef = useRef(0)
  const aiSpeakControllerRef = useRef<AbortController | null>(null)
  const tallyRequestRef = useRef(0)
  const pending = usePendingActions()
  const canManage = hasManagerRole(me?.role_code)

  useEffect(() => () => aiSpeakControllerRef.current?.abort(), [])

  const resetDrafts = () => {
    setSubject('')
    setSpeech('')
    setAiTopic('')
    setResText('')
    setTally(null)
    setSubjects([])
  }
  const open = async (id: string) => {
    const requestId = ++openRequestRef.current
    tallyRequestRef.current += 1
    aiSpeakControllerRef.current?.abort()
    resetDrafts()
    const next = await getMeeting(id)
    if (requestId === openRequestRef.current) setDetail(next)
    void listVoteSubjects(id).then((s) => {
      if (requestId === openRequestRef.current) setSubjects(s)
    }).catch(() => {})
  }
  const close = () => {
    openRequestRef.current += 1
    tallyRequestRef.current += 1
    aiSpeakControllerRef.current?.abort()
    aiSpeakControllerRef.current = null
    setAiSpeaking(false)
    setDetail(null)
    resetDrafts()
  }
  const refresh = async () => {
    const meetingId = detail?.meeting.id
    if (!meetingId) return
    const next = await getMeeting(meetingId)
    setDetail((current) => current?.meeting.id === meetingId ? next : current)
  }
  const inProgress = detail?.meeting.status === 'in_progress'

  const showTally = async (mid: string, subj: string) => {
    if (!subj) return
    const requestId = ++tallyRequestRef.current
    const next = await getTally(mid, subj)
    if (requestId === tallyRequestRef.current) {
      setTally(next)
      // 刚投过票的对象即时进下拉，无需重开会议（P1-8）。
      setSubjects((prev) => (prev.includes(subj) ? prev : [...prev, subj]))
    }
  }

  const columns: ProColumns<Meeting>[] = [
    { title: '主题', dataIndex: 'title' },
    {
      title: '状态',
      dataIndex: 'status',
      render: (_, r) => <Tag color={STATUS_COLOR[r.status] ?? 'default'}>{MEETING_STATUS[r.status] ?? r.status}</Tag>,
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
        toolBarRender={() => canManage ? [
          <ModalForm
            key="new"
            title="新建会议"
            width={420}
            trigger={<Button type="primary">新建会议</Button>}
            modalProps={{ destroyOnClose: true }}
            onFinish={async (values: { title: string }) => {
              await createMeeting(values.title.trim())
              message.success('已创建')
              actionRef.current?.reload()
              return true
            }}
          >
            <ProFormText
              name="title"
              label="会议主题"
              placeholder="请输入会议主题"
              rules={[{ required: true, message: '请输入会议主题' }, { max: 100, message: '主题不超过 100 字' }]}
            />
          </ModalForm>,
        ] : []}
      />

      <Drawer open={!!detail} onClose={close} width="min(640px, 100vw)"
        title={detail && `${detail.meeting.title}（${MEETING_STATUS[detail.meeting.status] ?? detail.meeting.status}）`}>
        {detail && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            {canManage && (
              <Space>
              {detail.meeting.status === 'scheduled' && (
                <Button type="primary" loading={pending.isPending(`meeting:${detail.meeting.id}:start`)} onClick={() => {
                  void pending.run(`meeting:${detail.meeting.id}:start`, async () => {
                    await setMeetingStatus(detail.meeting.id, 'in_progress')
                    message.success('会议开始')
                    await refresh()
                  }).catch(() => {})
                }}>开始会议</Button>
              )}
              {inProgress && (
                <Popconfirm
                  title="确认结束会议?"
                  description="结束后不可再发言、投票或生成纪要,且无法重新开启。"
                  okText="结束会议"
                  okButtonProps={{ danger: true }}
                  cancelText="取消"
                  onConfirm={() => pending.run(`meeting:${detail.meeting.id}:close`, async () => {
                    await setMeetingStatus(detail.meeting.id, 'closed')
                    message.success('会议结束')
                    await refresh()
                  }).catch(() => {})}
                >
                  <Button danger loading={pending.isPending(`meeting:${detail.meeting.id}:close`)}>结束会议</Button>
                </Popconfirm>
              )}
              </Space>
            )}

            <Card size="small" title="发言">
              <List size="small" dataSource={detail.discussions} locale={{ emptyText: '暂无发言' }}
                renderItem={(d) => (
                  <List.Item>
                    <Tag color={d.speaker_type === 'ai' ? 'blue' : 'default'}>{d.speaker_name}</Tag>
                    <Markdown>{d.content}</Markdown>
                  </List.Item>
                )} />
              {inProgress && (
                <Space direction="vertical" style={{ width: '100%', marginTop: 8 }} size={8}>
                  <Space.Compact style={{ width: '100%' }}>
                    <Input placeholder="真人发言…" value={speech}
                      onChange={(e) => setSpeech(e.target.value)}
                      onPressEnter={() => {
                        const content = speech.trim()
                        if (!content) return
                        void pending.run(`meeting:${detail.meeting.id}:discuss`, async () => {
                          await discuss(detail.meeting.id, content)
                          setSpeech('')
                          await refresh()
                        }).catch(() => {})
                      }} />
                    <Button loading={pending.isPending(`meeting:${detail.meeting.id}:discuss`)} onClick={() => {
                      const content = speech.trim()
                      if (!content) return
                      void pending.run(`meeting:${detail.meeting.id}:discuss`, async () => {
                        await discuss(detail.meeting.id, content)
                        setSpeech('')
                        await refresh()
                      }).catch(() => {})
                    }}>发言</Button>
                  </Space.Compact>
                  {canManage && (
                    <Space.Compact style={{ width: '100%' }}>
                      <Input placeholder="输入议题,让 AI 专家发言" value={aiTopic}
                        onChange={(e) => setAiTopic(e.target.value)} disabled={aiSpeaking} />
                      <Button type="primary" loading={aiSpeaking} onClick={async () => {
                        const topic = aiTopic.trim()
                        if (!topic || aiSpeakControllerRef.current) return
                        const controller = new AbortController()
                        aiSpeakControllerRef.current = controller
                        setAiSpeaking(true)
                        const streamId = `__streaming__-${detail.meeting.id}`
                        try {
                          await aiSpeak(detail.meeting.id, topic, (event, data) => {
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
                          }, { signal: controller.signal })
                          setAiTopic('')
                        } catch {
                          setDetail((prev) => prev && ({ ...prev, discussions: prev.discussions.filter((x) => x.id !== streamId) }))
                        } finally {
                          if (aiSpeakControllerRef.current === controller) {
                            aiSpeakControllerRef.current = null
                            setAiSpeaking(false)
                          }
                        }
                      }}>AI专家</Button>
                    </Space.Compact>
                  )}
                </Space>
              )}
            </Card>

            {inProgress && (
              <Card size="small" title="投票（真人票决定，AI票仅参考）">
                <Space.Compact style={{ width: '100%' }}>
                  <AutoComplete
                    style={{ width: '100%' }}
                    placeholder="表决对象（可选已有或新建）"
                    value={subject}
                    onChange={setSubject}
                    options={subjects.map((s) => ({ value: s }))}
                    filterOption={(input, option) =>
                      (option?.value ?? '').toLowerCase().includes(input.toLowerCase())
                    }
                  />
                  <Button loading={pending.isPending(`meeting:${detail.meeting.id}:vote:approve`)} onClick={() => {
                    const value = subject.trim()
                    if (!value) return
                    setSubject(value)
                    void pending.run(`meeting:${detail.meeting.id}:vote:approve`, async () => {
                      await vote(detail.meeting.id, value, 'approve')
                      await showTally(detail.meeting.id, value)
                    }).catch(() => {})
                  }}>赞成</Button>
                  <Button danger loading={pending.isPending(`meeting:${detail.meeting.id}:vote:reject`)} onClick={() => {
                    const value = subject.trim()
                    if (!value) return
                    setSubject(value)
                    void pending.run(`meeting:${detail.meeting.id}:vote:reject`, async () => {
                      await vote(detail.meeting.id, value, 'reject')
                      await showTally(detail.meeting.id, value)
                    }).catch(() => {})
                  }}>反对</Button>
                  {canManage && <Button type="primary" loading={pending.isPending(`meeting:${detail.meeting.id}:ai-vote`)} onClick={() => {
                    const value = subject.trim()
                    if (!value) return
                    setSubject(value)
                    void pending.run(`meeting:${detail.meeting.id}:ai-vote`, async () => {
                      await aiVote(detail.meeting.id, value)
                      await showTally(detail.meeting.id, value)
                    }).catch(() => {})
                  }}>AI参考票</Button>}
                  <Button onClick={() => { const value = subject.trim(); if (value) { setSubject(value); void showTally(detail.meeting.id, value) } }}>统计</Button>
                </Space.Compact>
                {tally && tally.subject === subject && (
                  <div style={{ marginTop: 8 }}>
                    <Tag color={tally.human_passed ? 'success' : 'default'}>
                      真人票{tally.human_passed ? '通过' : '未过'}
                    </Tag>
                    <span>真人 {formatVotes(tally.human)} · AI参考 {formatVotes(tally.ai)}</span>
                  </div>
                )}
              </Card>
            )}

            <Card size="small" title="会议纪要"
              extra={canManage ? <Button
                size="small"
                disabled={detail.discussions.length === 0}
                loading={pending.isPending(`meeting:${detail.meeting.id}:minutes`)}
                onClick={() => {
                  const key = `meeting:${detail.meeting.id}:minutes`
                  void pending.run(key, async () => {
                    message.loading({ content: '生成中…', key, duration: 0 })
                    try {
                      await generateMinutes(detail.meeting.id)
                      message.success({ content: '已生成', key })
                      await refresh()
                    } catch (error) {
                      message.destroy(key)
                      throw error
                    }
                  }).catch(() => {})
                }}
              >生成纪要</Button> : undefined}>
              <Markdown>{detail.meeting.summary || '（暂无纪要）'}</Markdown>
            </Card>

            <Card size="small" title="决议（须真人确认生效）">
              <List size="small" dataSource={detail.resolutions} locale={{ emptyText: '暂无决议' }}
                renderItem={(r) => (
                  <List.Item actions={canManage ? [
                    r.is_confirmed
                      ? (r.converted_task_id
                          ? <Tag color="success" key="t">已转任务卡</Tag>
                          : <Button key="cv" type="link" size="small" loading={pending.isPending(`resolution:${r.id}:convert`)} onClick={() => {
                            void pending.run(`resolution:${r.id}:convert`, async () => {
                              await convertResolution(r.id)
                              message.success('已转任务卡')
                              await refresh()
                            }).catch(() => {})
                          }}>转任务卡</Button>)
                      : <Button key="cf" type="link" size="small" loading={pending.isPending(`resolution:${r.id}:confirm`)} onClick={() => {
                        void pending.run(`resolution:${r.id}:confirm`, async () => {
                          await confirmResolution(r.id)
                          message.success('已确认生效')
                          await refresh()
                        }).catch(() => {})
                      }}>确认生效</Button>,
                  ] : []}>
                    <Tag color={r.is_confirmed ? 'green' : 'orange'}>{r.is_confirmed ? '已确认' : '待确认'}</Tag>
                    <Markdown>{r.content}</Markdown>
                  </List.Item>
                )} />
              {canManage && <Space.Compact style={{ width: '100%', marginTop: 8 }}>
                <Input placeholder="登记决议内容" value={resText} onChange={(e) => setResText(e.target.value)} />
                <Button loading={pending.isPending(`meeting:${detail.meeting.id}:resolution`)} onClick={() => {
                  const content = resText.trim()
                  if (!content) return
                  void pending.run(`meeting:${detail.meeting.id}:resolution`, async () => {
                    await createResolution(detail.meeting.id, content)
                    setResText('')
                    await refresh()
                  }).catch(() => {})
                }}>登记决议</Button>
              </Space.Compact>}
            </Card>
          </Space>
        )}
      </Drawer>
    </PageContainer>
  )
}

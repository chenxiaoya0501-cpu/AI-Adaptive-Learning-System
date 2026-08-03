import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert,
  Button,
  Checkbox,
  Input,
  Modal,
  Spin,
  Typography,
  message,
} from 'antd'
import {
  ArrowLeftOutlined,
  CheckOutlined,
  LeftOutlined,
  RightOutlined,
  SaveOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import {
  BANK_LABELS,
  STATUS_LABELS,
  TYPE_LABELS,
  testsApi,
  type AnswerPayload,
  type TakingSession,
  type TestQuestionPublic,
} from '../../api/tests'
import { RichQuestionContent, normalizeOptions } from '../../components/RichQuestionContent'
import './examTaking.css'

function apiError(e: any, fallback: string) {
  const d = e?.response?.data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map((x) => x.msg || JSON.stringify(x)).join('；')
  return fallback
}

type LocalAnswer = {
  selected_option?: string | null
  answer_text?: string | null
  is_marked_uncertain?: boolean
}

function draftKey(paperId: number) {
  return `exam_draft_${paperId}`
}

function isAnswered(a?: LocalAnswer | null) {
  if (!a) return false
  if (a.selected_option && String(a.selected_option).trim()) return true
  if (a.answer_text && String(a.answer_text).trim()) return true
  return false
}

export default function Taking() {
  const { paperId: paperIdParam } = useParams()
  const paperId = Number(paperIdParam)
  const navigate = useNavigate()

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [session, setSession] = useState<TakingSession | null>(null)
  const [index, setIndex] = useState(0)
  const [answers, setAnswers] = useState<Record<number, LocalAnswer>>({})
  const [saveHint, setSaveHint] = useState('答案将自动保存')
  const saveTimers = useRef<Record<number, ReturnType<typeof setTimeout>>>({})

  const questions = session?.paper.questions || []
  const current = questions[index] as TestQuestionPublic | undefined
  const readonly = Boolean(session?.readonly)

  const load = useCallback(async () => {
    if (!paperId) return
    setLoading(true)
    try {
      const { data } = await testsApi.start(paperId)
      setSession(data)
      const map: Record<number, LocalAnswer> = {}
      for (const a of data.answers) {
        map[a.test_question_id] = {
          selected_option: a.selected_option,
          answer_text: a.answer_text,
          is_marked_uncertain: a.is_marked_uncertain,
        }
      }
      // 本地草稿补全（仅可编辑时）
      if (!data.readonly) {
        try {
          const raw = localStorage.getItem(draftKey(paperId))
          if (raw) {
            const local = JSON.parse(raw) as Record<number, LocalAnswer>
            for (const [qid, val] of Object.entries(local)) {
              const id = Number(qid)
              if (!isAnswered(map[id]) && isAnswered(val)) map[id] = val
            }
          }
        } catch {
          /* ignore */
        }
      }
      setAnswers(map)
    } catch (e: any) {
      message.error(apiError(e, '加载答题页失败'))
    } finally {
      setLoading(false)
    }
  }, [paperId])

  useEffect(() => {
    load()
    return () => {
      Object.values(saveTimers.current).forEach(clearTimeout)
    }
  }, [load])

  useEffect(() => {
    if (!paperId || readonly) return
    localStorage.setItem(draftKey(paperId), JSON.stringify(answers))
  }, [answers, paperId, readonly])

  const answeredCount = useMemo(
    () => questions.filter((q) => isAnswered(answers[q.id])).length,
    [questions, answers],
  )

  const persistAnswer = useCallback(
    async (qid: number, payload: LocalAnswer) => {
      if (!paperId || readonly) return
      setSaving(true)
      try {
        const body: AnswerPayload = {
          selected_option: payload.selected_option ?? null,
          answer_text: payload.answer_text ?? null,
          is_marked_uncertain: Boolean(payload.is_marked_uncertain),
        }
        await testsApi.saveAnswer(paperId, qid, body)
        setSaveHint('已自动保存')
      } catch (e: any) {
        setSaveHint('保存失败，已留在本地')
        message.error(apiError(e, '暂存失败'))
      } finally {
        setSaving(false)
      }
    },
    [paperId, readonly],
  )

  const scheduleSave = useCallback(
    (qid: number, payload: LocalAnswer) => {
      if (readonly) return
      setSaveHint('保存中…')
      if (saveTimers.current[qid]) clearTimeout(saveTimers.current[qid])
      saveTimers.current[qid] = setTimeout(() => {
        persistAnswer(qid, payload)
      }, 450)
    },
    [persistAnswer, readonly],
  )

  const updateAnswer = (qid: number, patch: Partial<LocalAnswer>, immediate = false) => {
    setAnswers((prev) => {
      const next = { ...prev[qid], ...patch }
      const merged = { ...prev, [qid]: next }
      if (immediate) {
        void persistAnswer(qid, next)
      } else {
        scheduleSave(qid, next)
      }
      return merged
    })
  }

  const go = (i: number) => {
    if (i < 0 || i >= questions.length) return
    setIndex(i)
  }

  const saveProgress = async () => {
    if (!paperId || readonly) return
    // 清掉节流定时器，改走批量接口，避免并发单题请求把库锁死
    Object.values(saveTimers.current).forEach(clearTimeout)
    saveTimers.current = {}
    setSaving(true)
    setSaveHint('正在保存…')
    try {
      const targets = questions.filter(
        (q) => isAnswered(answers[q.id]) || q.id === current?.id,
      )
      const payload = targets.map((q) => {
        const a = answers[q.id] || {}
        return {
          test_question_id: q.id,
          selected_option: a.selected_option ?? null,
          answer_text: a.answer_text ?? null,
          is_marked_uncertain: Boolean(a.is_marked_uncertain),
        }
      })
      const { data } = await testsApi.saveProgress(paperId, payload)
      localStorage.setItem(draftKey(paperId), JSON.stringify(answers))
      setSession(data)
      setSaveHint('已保存，可稍后继续测试')
      message.success('作答已保存，可返回后点「继续测试」接着做')
    } catch (e: any) {
      setSaveHint('保存失败，已留在本地')
      message.error(apiError(e, '保存失败'))
    } finally {
      setSaving(false)
    }
  }

  const submit = () => {
    if (!session || !paperId) return
    const unanswered = questions.filter((q) => !isAnswered(answers[q.id])).length
    Modal.confirm({
      title: '确认交卷？',
      content:
        unanswered > 0
          ? `还有 ${unanswered} 题未作答，交卷后不可再修改。`
          : '交卷后不可再修改答案。',
      okText: '确认交卷',
      cancelText: '继续答题',
      onOk: async () => {
        setSubmitting(true)
        try {
          // 交卷前刷一遍当前题
          if (current) {
            await persistAnswer(current.id, answers[current.id] || {})
          }
          const { data } = await testsApi.submit(paperId)
          localStorage.removeItem(draftKey(paperId))
          message.success(data.message || '交卷成功，已自动批改')
          navigate(`/exam/result/${paperId}`, { replace: true })
        } catch (e: any) {
          message.error(apiError(e, '交卷失败'))
          throw e
        } finally {
          setSubmitting(false)
        }
      },
    })
  }

  if (loading) {
    return (
      <div className="taking-page taking-page--center">
        <Spin tip="正在进入测试…" />
      </div>
    )
  }

  if (!session || !current) {
    return (
      <div className="taking-page">
        <Alert
          type="error"
          showIcon
          message="试卷不存在或无法作答"
          action={
            <Button size="small" onClick={() => navigate('/exam')}>
              返回测评
            </Button>
          }
        />
      </div>
    )
  }

  const curAns = answers[current.id] || {}
  const opts = normalizeOptions(current.options)

  return (
    <div className="taking-page">
      <div className="taking-topbar">
        <div>
          <Button
            type="link"
            icon={<ArrowLeftOutlined />}
            onClick={() =>
              navigate(`/exam?goalId=${session.paper.goal_id}&paperId=${session.paper.id}`)
            }
            style={{ paddingLeft: 0 }}
          >
            返回预览
          </Button>
          <h2 className="taking-topbar__title">
            {session.paper.title || `试卷 #${session.paper.id}`}
          </h2>
          <p className="taking-topbar__meta">
            {BANK_LABELS[session.paper.bank_type] || session.paper.bank_type} ·{' '}
            {STATUS_LABELS[session.paper.status] || session.paper.status}
            {' · '}已答 {answeredCount}/{questions.length}
            {readonly && session.paper.earned_score != null
              ? ` · 选择题得分 ${session.paper.earned_score}`
              : ''}
          </p>
        </div>
        <div className="taking-topbar__actions">
          <span className="taking-save-hint">{saving ? '保存中…' : saveHint}</span>
          {!readonly ? (
            <>
              <Button
                icon={<SaveOutlined />}
                loading={saving}
                disabled={submitting}
                onClick={() => void saveProgress()}
              >
                保存
              </Button>
              <Button type="primary" loading={submitting} onClick={submit} icon={<CheckOutlined />}>
                交卷
              </Button>
            </>
          ) : (
            <Button type="primary" ghost onClick={() => navigate('/exam')}>
              返回测评
            </Button>
          )}
        </div>
      </div>

      {readonly ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="该卷已交卷，仅可查看作答（不可再改）。"
        />
      ) : null}

      <div className="taking-layout">
        <aside className="taking-nav">
          <h3 className="taking-nav__title">答题卡</h3>
          <div className="taking-nav__grid">
            {questions.map((q, i) => {
              const a = answers[q.id]
              const cls = [
                'taking-nav__btn',
                i === index ? 'is-current' : '',
                isAnswered(a) ? 'is-answered' : '',
                a?.is_marked_uncertain ? 'is-uncertain' : '',
              ]
                .filter(Boolean)
                .join(' ')
              return (
                <button key={q.id} type="button" className={cls} onClick={() => go(i)}>
                  {q.seq}
                </button>
              )
            })}
          </div>
          <div className="taking-nav__legend">
            <span>青绿 = 已答</span>
            <span>橙色 = 不确定</span>
            <span>深色 = 当前题</span>
          </div>
        </aside>

        <section className="taking-main">
          <div className="taking-q-meta">
            第 {current.seq} 题 · {TYPE_LABELS[current.question_type] || current.question_type} ·{' '}
            {current.score} 分
            {current.primary_kp_id ? ` · ${current.primary_kp_id}` : ''}
          </div>

          <div className="taking-q-stem">
            <RichQuestionContent
              text={current.content}
              paperId={current.source_exam_paper_id}
            />
          </div>

          {current.question_type === 'choice' ? (
            <div className="taking-choice">
              {opts.map(([k, v]) => {
                const selected = curAns.selected_option === k
                return (
                  <button
                    key={k}
                    type="button"
                    className={`taking-choice__item${selected ? ' is-selected' : ''}`}
                    disabled={readonly}
                    onClick={() => updateAnswer(current.id, { selected_option: k }, true)}
                  >
                    <span className="taking-choice__key">{k}</span>
                    <span className="taking-choice__body">
                      <RichQuestionContent text={v} paperId={current.source_exam_paper_id} />
                    </span>
                  </button>
                )
              })}
            </div>
          ) : current.question_type === 'fill' ? (
            <Input
              size="large"
              placeholder="请输入答案"
              value={curAns.answer_text || ''}
              disabled={readonly}
              onChange={(e) => updateAnswer(current.id, { answer_text: e.target.value })}
            />
          ) : (
            <Input.TextArea
              rows={8}
              placeholder="请输入解答过程与答案"
              value={curAns.answer_text || ''}
              disabled={readonly}
              onChange={(e) => updateAnswer(current.id, { answer_text: e.target.value })}
            />
          )}

          <div style={{ marginTop: 14 }}>
            <Checkbox
              checked={Boolean(curAns.is_marked_uncertain)}
              disabled={readonly}
              onChange={(e) =>
                updateAnswer(current.id, { is_marked_uncertain: e.target.checked }, true)
              }
            >
              标记为不确定
            </Checkbox>
          </div>

          <div className="taking-footer">
            <Button icon={<LeftOutlined />} disabled={index <= 0} onClick={() => go(index - 1)}>
              上一题
            </Button>
            <Typography.Text type="secondary">
              {index + 1} / {questions.length}
            </Typography.Text>
            {index < questions.length - 1 ? (
              <Button type="primary" onClick={() => go(index + 1)}>
                下一题 <RightOutlined />
              </Button>
            ) : readonly ? (
              <Button type="primary" onClick={() => navigate('/exam')}>
                完成查看
              </Button>
            ) : (
              <Button type="primary" loading={submitting} onClick={submit}>
                交卷
              </Button>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}

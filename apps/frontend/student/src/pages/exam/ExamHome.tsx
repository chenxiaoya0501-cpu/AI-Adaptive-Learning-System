import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Empty,
  Modal,
  Radio,
  Space,
  Spin,
  Typography,
  message,
} from 'antd'
import {
  ArrowLeftOutlined,
  DeleteOutlined,
  FileTextOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { goalsApi, type LearningGoal } from '../../api/goals'
import {
  BANK_LABELS,
  STATUS_LABELS,
  TYPE_LABELS,
  isPaperTested,
  isPaperTesting,
  testsApi,
  type AssemblePreview,
  type TestPaperDetail,
  type TestPaperSummary,
} from '../../api/tests'
import { ExamQuestionBody } from '../../components/RichQuestionContent'
import './examHome.css'

function apiError(e: any, fallback: string) {
  const d = e?.response?.data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map((x) => x.msg || JSON.stringify(x)).join('；')
  return fallback
}

export default function ExamHome() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const goalIdParam = params.get('goalId')
  const paperIdParam = params.get('paperId')

  const [loading, setLoading] = useState(true)
  const [assembling, setAssembling] = useState(false)
  const [goal, setGoal] = useState<LearningGoal | null>(null)
  const [preview, setPreview] = useState<AssemblePreview | null>(null)
  const [bankType, setBankType] = useState<'real' | 'mock'>('real')
  const [history, setHistory] = useState<TestPaperSummary[]>([])
  const [paper, setPaper] = useState<TestPaperDetail | null>(null)

  const goalId = useMemo(() => {
    if (goalIdParam) return Number(goalIdParam)
    return goal?.id ?? null
  }, [goalIdParam, goal?.id])

  const historyStats = useMemo(() => {
    let notTested = 0
    let testing = 0
    let tested = 0
    for (const h of history) {
      if (isPaperTested(h.status)) tested += 1
      else if (isPaperTesting(h.status)) testing += 1
      else notTested += 1
    }
    return { total: history.length, notTested, testing, tested }
  }, [history])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      let g: LearningGoal | null = null
      if (goalIdParam) {
        const { data } = await goalsApi.get(Number(goalIdParam))
        g = data
      } else {
        const { data } = await goalsApi.primary()
        g = data
      }
      setGoal(g)
      if (!g) {
        setPreview(null)
        setHistory([])
        setPaper(null)
        return
      }
      const [pv, hist] = await Promise.all([
        testsApi.preview(g.id),
        testsApi.list(g.id),
      ])
      setPreview(pv.data)
      setHistory(hist.data)
    } catch (e: any) {
      message.error(apiError(e, '加载测评页失败'))
    } finally {
      setLoading(false)
    }
  }, [goalIdParam])

  useEffect(() => {
    load()
  }, [load])

  // 仅切换 paperId 时拉取试卷，不做整页 loading，避免滚回顶部
  useEffect(() => {
    if (!paperIdParam) return
    const id = Number(paperIdParam)
    if (!id || Number.isNaN(id)) return
    if (paper?.id === id) return
    let cancelled = false
    ;(async () => {
      try {
        const { data } = await testsApi.get(id)
        if (!cancelled) setPaper(data)
      } catch (e: any) {
        if (!cancelled) message.error(apiError(e, '加载试卷失败'))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [paperIdParam, paper?.id])

  const assemble = async () => {
    if (!goalId) return
    if (!preview?.readiness_ok) {
      message.warning(preview?.readiness_messages?.[0] || '当前无法组卷')
      return
    }
    setAssembling(true)
    try {
      const { data } = await testsApi.assemble({
        goal_id: goalId,
        bank_type: bankType,
      })
      setPaper(data)
      const visibleWarnings = (data.warnings || []).filter(
        (w) => !/draft|审核发布/.test(w),
      )
      const shortage = Boolean(
        data.degraded ||
          visibleWarnings.some((w) => w.includes('题源不足') || w.includes('仅抽到')),
      )
      if (shortage) {
        message.warning('已组卷，但题源略有不足，请查看提示')
      } else if (visibleWarnings.length) {
        message.success('组卷成功（有提示，请查看下方说明）')
      } else {
        message.success('组卷成功')
      }
      const hist = await testsApi.list(goalId)
      setHistory(hist.data)
      navigate(`/exam?goalId=${goalId}&paperId=${data.id}`, {
        replace: true,
        preventScrollReset: true,
      })
    } catch (e: any) {
      message.error(apiError(e, '组卷失败'))
    } finally {
      setAssembling(false)
    }
  }

  const openPaper = async (id: number) => {
    if (paper?.id === id) return
    const y = window.scrollY
    try {
      const { data } = await testsApi.get(id)
      setPaper(data)
      navigate(`/exam?goalId=${data.goal_id}&paperId=${id}`, {
        replace: true,
        preventScrollReset: true,
      })
      // 布局变化后再钉回原滚动位置
      requestAnimationFrame(() => {
        window.scrollTo({ top: y, left: 0, behavior: 'auto' })
      })
    } catch (e: any) {
      message.error(apiError(e, '加载试卷失败'))
    }
  }

  const removePaper = (h: TestPaperSummary) => {
    Modal.confirm({
      title: '删除该组卷记录？',
      content: '删除后不可恢复。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          await testsApi.delete(h.id)
          setHistory((prev) => prev.filter((x) => x.id !== h.id))
          if (paper?.id === h.id) {
            setPaper(null)
            navigate(`/exam?goalId=${h.goal_id}`, { replace: true })
          }
          message.success('已删除')
        } catch (e: any) {
          message.error(apiError(e, '删除失败'))
          throw e
        }
      },
    })
  }

  if (loading) {
    return (
      <div className="exam-page exam-page--center">
        <Spin tip="加载中…" />
      </div>
    )
  }

  if (!goal) {
    return (
      <div className="exam-page">
        <Empty description="还没有主目标，请先创建学习目标">
          <Button type="primary" onClick={() => navigate('/goals/new')}>
            去创建目标
          </Button>
        </Empty>
      </div>
    )
  }

  return (
    <div className="exam-page">
      <div className="exam-header">
        <div>
          <Button
            type="link"
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/goals')}
            style={{ paddingLeft: 0 }}
          >
            返回目标
          </Button>
          <Typography.Title level={3} style={{ margin: '4px 0 0' }}>
            诊断测评
          </Typography.Title>
          <Typography.Text type="secondary">
            按管理端平均结构模板出题；题源可选真题库或模拟题库。范围=本册已勾选章 + 此前各册（七/八年级等）全部知识点
          </Typography.Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={load}>
          刷新
        </Button>
      </div>

      <section className="exam-card">
        <h3 className="exam-card__title">当前目标</h3>
        <div className="exam-meta">
          <div>
            <strong>{goal.title || `${goal.exam_type}${goal.subject}冲${goal.target_score}`}</strong>
            {goal.is_primary ? <span className="exam-tag">主目标</span> : null}
          </div>
          <div>
            {goal.grade_stage} · 本册已选 {goal.learned_chapter_count} 章
            {preview?.learned_kp_count
              ? ` · 测评覆盖约 ${preview.learned_kp_count} 知识点（含此前各册）`
              : goal.learned_kp_count
                ? ` · 约 ${goal.learned_kp_count} 知识点`
                : ''}
            {goal.region ? ` · ${goal.region}` : ''}
          </div>
        </div>
      </section>

      <section className="exam-card">
        <h3 className="exam-card__title">结构模板（平均模板）</h3>
        {preview?.template_name ? (
          <>
            <p className="exam-muted">
              {preview.template_name}
              {preview.template_status ? ` · ${preview.template_status}` : ''}
              {preview.total_score ? ` · 满分 ${preview.total_score}` : ''}
            </p>
            <div className="exam-type-row">
              {(preview.type_structure || []).map((t) => (
                <div key={t.question_type} className="exam-type-chip">
                  <span>{TYPE_LABELS[t.question_type] || t.question_type}</span>
                  <strong>
                    {t.count} 题 / {t.subtotal} 分
                  </strong>
                </div>
              ))}
            </div>
            <Alert
              type="info"
              showIcon
              style={{ marginTop: 12 }}
              message="出题规则"
              description="各题型题数与总分保持模板不变。已学范围含：当前年级阶段之前各册全部 + 本册已勾选章；未学章不参与；占比在已学知识点上同比例放大后再抽题。"
            />
          </>
        ) : (
          <Alert type="warning" showIcon message="暂无可用平均模板，请先在管理端生成并设为默认" />
        )}
        {preview?.readiness_messages?.length ? (
          <Alert
            style={{ marginTop: 12 }}
            type={preview.readiness_ok ? 'info' : 'warning'}
            showIcon
            message={preview.readiness_messages.join('；')}
          />
        ) : null}
      </section>

      <section className="exam-card">
        <h3 className="exam-card__title">选择题库</h3>
        <Radio.Group
          value={bankType}
          onChange={(e) => setBankType(e.target.value)}
          optionType="button"
          buttonStyle="solid"
          options={[
            { label: '真题库', value: 'real' },
            { label: '模拟题库', value: 'mock' },
          ]}
        />
        <p className="exam-muted" style={{ marginTop: 10 }}>
          真题 → 仅从真题题目列表抽题；模拟题 → 仅从模拟题库列表抽题。结构均参考同一平均模板。
        </p>
        <Space style={{ marginTop: 16 }}>
          <Button
            type="primary"
            size="large"
            loading={assembling}
            disabled={!preview?.readiness_ok}
            onClick={assemble}
          >
            开始组卷测评
          </Button>
          <Button onClick={() => navigate(`/goals/${goal.id}/edit`)}>调整已学章节</Button>
        </Space>
      </section>

      {paper && (
        <section className="exam-card exam-card--result">
          <div className="exam-card__head">
            <h3 className="exam-card__title" style={{ margin: 0 }}>
              <FileTextOutlined /> {paper.title || `试卷 #${paper.id}`}
            </h3>
            <span className="exam-tag">
              {BANK_LABELS[paper.bank_type] || paper.bank_type} ·{' '}
              {STATUS_LABELS[paper.status] || paper.status}
            </span>
          </div>
          <div className="exam-result-summary">
            <p className="exam-result-summary__stats">
              共 <strong>{paper.question_count}</strong> 题，满分{' '}
              <strong>{paper.total_score}</strong>
              {paper.degraded ? (
                <span className="exam-result-summary__note"> · 已降级调整题量</span>
              ) : null}
            </p>
            {(() => {
              // 当前版本不做审核发布，隐藏 draft 相关提示
              const tips = (paper.warnings || []).filter(
                (w) => !/draft|审核发布/.test(w),
              )
              if (!tips.length) return null
              return (
                <Alert
                  type="warning"
                  showIcon
                  message="组卷提示"
                  description={
                    <ul style={{ margin: 0, paddingLeft: 18 }}>
                      {tips.map((w) => (
                        <li key={w}>{w}</li>
                      ))}
                    </ul>
                  }
                />
              )
            })()}
            <Alert type="success" showIcon message="组卷已完成（题目快照已保存）。" />
          </div>
          <div className="exam-q-scroll">
            <ol className="exam-q-list">
              {paper.questions.map((q) => (
                <li key={q.id} className="exam-q-item">
                  <div className="exam-q-item__meta">
                    第 {q.seq} 题 · {TYPE_LABELS[q.question_type] || q.question_type} · {q.score}{' '}
                    分
                    {q.primary_kp_id ? ` · ${q.primary_kp_id}` : ''}
                  </div>
                  <div className="exam-q-item__content">
                    <ExamQuestionBody
                      content={q.content}
                      options={q.options}
                      paperId={q.source_exam_paper_id}
                    />
                  </div>
                </li>
              ))}
            </ol>
          </div>
          <div className="exam-start-bar">
            {isPaperTested(paper.status) ? (
              <Space size="middle">
                <Button
                  type="primary"
                  size="large"
                  onClick={() => navigate(`/exam/result/${paper.id}`)}
                >
                  查看批改结果
                </Button>
                <Button size="large" onClick={() => navigate(`/exam/taking/${paper.id}`)}>
                  查看作答
                </Button>
              </Space>
            ) : (
              <Button
                type="primary"
                size="large"
                onClick={() => navigate(`/exam/taking/${paper.id}`)}
              >
                {isPaperTesting(paper.status) ? '继续测试' : '开始测试'}
              </Button>
            )}
          </div>
        </section>
      )}

      <section className="exam-card">
        <div className="exam-history__head">
          <h3 className="exam-card__title" style={{ margin: 0 }}>
            历史组卷
          </h3>
          {historyStats.total > 0 ? (
            <div className="exam-history__stats" aria-label="组卷状态统计">
              <span>共 {historyStats.total} 套</span>
              <span className="exam-history__stat exam-history__stat--idle">
                未测评 {historyStats.notTested}
              </span>
              <span className="exam-history__stat exam-history__stat--testing">
                测评中 {historyStats.testing}
              </span>
              <span className="exam-history__stat exam-history__stat--tested">
                已测评 {historyStats.tested}
              </span>
            </div>
          ) : null}
        </div>
        {!history.length ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无历史组卷" />
        ) : (
          <ul className="exam-history">
            {history.map((h) => {
              const selected = paper?.id === h.id
              return (
              <li
                key={h.id}
                className={`exam-history__row${selected ? ' is-selected' : ''}`}
              >
                <button
                  type="button"
                  className={`exam-history__btn${selected ? ' is-selected' : ''}`}
                  aria-pressed={selected}
                  onClick={() => openPaper(h.id)}
                >
                  <span>
                    {h.title || `试卷 #${h.id}`}
                    <span className="exam-muted">
                      {' '}
                      · {BANK_LABELS[h.bank_type] || h.bank_type} ·{' '}
                      <span
                        className={`exam-history__status exam-history__status--${
                          isPaperTested(h.status)
                            ? 'tested'
                            : isPaperTesting(h.status)
                              ? 'testing'
                              : 'idle'
                        }`}
                      >
                        {STATUS_LABELS[h.status] || h.status}
                      </span>
                      {h.created_at ? ` · ${String(h.created_at).slice(0, 16).replace('T', ' ')}` : ''}
                    </span>
                  </span>
                  <span>
                    {h.question_count} 题 / {h.total_score} 分
                  </span>
                </button>
                <Button
                  type="text"
                  danger
                  size="small"
                  icon={<DeleteOutlined />}
                  aria-label="删除组卷"
                  onClick={() => removePaper(h)}
                />
              </li>
              )
            })}
          </ul>
        )}
      </section>
    </div>
  )
}

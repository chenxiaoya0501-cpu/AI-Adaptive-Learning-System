import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Empty, Modal, Typography, message } from 'antd'
import {
  CopyOutlined,
  EditOutlined,
  FormOutlined,
  PlusOutlined,
  StarFilled,
  StarOutlined,
  InboxOutlined,
  AimOutlined,
  BookOutlined,
  CalendarOutlined,
  ApartmentOutlined,
  CompassOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { goalsApi, type LearningGoal } from '../../api/goals'
import './goalList.css'

function apiError(e: any, fallback: string) {
  const d = e?.response?.data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map((x) => x.msg || JSON.stringify(x)).join('；')
  return fallback
}

export default function GoalList() {
  const [goals, setGoals] = useState<LearningGoal[]>([])
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await goalsApi.list('active')
      setGoals(data)
    } catch (e: any) {
      message.error(apiError(e, '加载目标失败'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const setPrimary = (g: LearningGoal) => {
    Modal.confirm({
      title: '切换主目标？',
      content: '之后的出题与路径将按新目标进行。',
      onOk: async () => {
        await goalsApi.setPrimary(g.id)
        message.success('已设为主目标')
        load()
      },
    })
  }

  const archive = (g: LearningGoal) => {
    Modal.confirm({
      title: '归档该目标？',
      content: '归档后不再出现在列表中。',
      onOk: async () => {
        await goalsApi.archive(g.id)
        message.success('已归档')
        load()
      },
    })
  }

  const copy = async (g: LearningGoal) => {
    try {
      await goalsApi.copy(g.id)
      message.success('已复制')
      load()
    } catch (e: any) {
      message.error(apiError(e, '复制失败'))
    }
  }

  const ack = async (g: LearningGoal) => {
    await goalsApi.ackReplan(g.id)
    message.success('已关闭提示')
    load()
  }

  const startAssess = async (g: LearningGoal) => {
    if (!g.learned_chapter_count) {
      message.warning('请先编辑目标并勾选已学章节，再开始评测')
      return
    }
    // 非主目标：先切主目标，后续组卷按主目标读取
    if (!g.is_primary) {
      Modal.confirm({
        title: '将该目标设为主目标并开始评测？',
        content: '之后的出题与路径将按此目标进行。',
        okText: '开始评测',
        onOk: async () => {
          await goalsApi.setPrimary(g.id)
          navigate(`/exam?goalId=${g.id}`)
        },
      })
      return
    }
    navigate(`/exam?goalId=${g.id}`)
  }

  return (
    <div className="goal-list-page">
      <div className="goal-list-header">
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>
            学习目标
          </Typography.Title>
          <Typography.Text type="secondary">创建后的目标会出现在这里，可随时切换主目标</Typography.Text>
        </div>
        <Button type="primary" size="large" icon={<PlusOutlined />} onClick={() => navigate('/goals/new')}>
          新建目标
        </Button>
      </div>

      {!loading && goals.length === 0 && (
        <div className="goal-empty">
          <Empty description="还没有学习目标">
            <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/goals/new')}>
              创建第一个学习目标
            </Button>
          </Empty>
        </div>
      )}

      <div className="goal-card-grid">
        {goals.map((g) => {
          const title = g.title || `${g.exam_type}${g.subject}冲${g.target_score}`
          return (
            <article
              key={g.id}
              className={`goal-card${g.is_primary ? ' goal-card--primary' : ''}${loading ? ' goal-card--loading' : ''}`}
            >
              <div className="goal-card__accent" />
              <div className="goal-card__body">
                <div className="goal-card__top">
                  <div className="goal-card__title-row">
                    <h3 className="goal-card__title">{title}</h3>
                    <div className="goal-card__badges">
                      {g.is_primary && (
                        <span className="goal-badge goal-badge--primary">
                          <StarFilled /> 主目标
                        </span>
                      )}
                      <span className="goal-badge">
                        {g.mastery_status === 'assessed' ? '已测评' : '待测评'}
                      </span>
                      {g.needs_replan && <span className="goal-badge goal-badge--warn">建议重测</span>}
                    </div>
                  </div>
                  <div className="goal-card__score">
                    <span className="goal-card__score-label">目标分</span>
                    <span className="goal-card__score-value">{g.target_score}</span>
                  </div>
                </div>

                {g.needs_replan && (
                  <Alert
                    type="warning"
                    showIcon
                    style={{ marginBottom: 14 }}
                    message="已学章节或目标分已变更，建议重测或重规划"
                    action={
                      <Button size="small" type="link" onClick={() => ack(g)}>
                        知道了
                      </Button>
                    }
                  />
                )}

                <div className="goal-card__meta">
                  <div className="goal-meta-item">
                    <AimOutlined />
                    <span>
                      {g.exam_type} · {g.subject}
                      {g.region ? ` · ${g.region}` : ''}
                    </span>
                  </div>
                  <div className="goal-meta-item">
                    <BookOutlined />
                    <span>
                      {g.grade_stage} · 本册已选 {g.learned_chapter_count} 章
                      {g.learned_kp_count > 0 ? ` · 测评覆盖约 ${g.learned_kp_count} 知识点` : ''}
                    </span>
                  </div>
                  {(g.exam_date || g.daily_study_minutes != null) && (
                    <div className="goal-meta-item">
                      <CalendarOutlined />
                      <span>
                        {g.exam_date ? `考试日 ${g.exam_date}` : ''}
                        {g.exam_date && g.daily_study_minutes != null ? ' · ' : ''}
                        {g.daily_study_minutes != null ? `每日 ${g.daily_study_minutes} 分钟` : ''}
                      </span>
                    </div>
                  )}
                </div>

                {!g.learned_chapter_count && (
                  <p className="goal-card__hint">未勾选已学章节时，正式测评将不可启动</p>
                )}

                {(() => {
                  const results = (g.recent_results || []).filter(
                    (r) =>
                      r.event_type === 'graded' ||
                      r.event_type === 'taking' ||
                      r.title === '批改完成' ||
                      r.title === '答题中',
                  )
                  if (!results.length) return null
                  return (
                  <div className="goal-results">
                    <div className="goal-results__title">结果记录</div>
                    <ul className="goal-results__list">
                      {results.slice(0, 4).map((r) => {
                        const isTaking =
                          r.event_type === 'taking' || r.title === '答题中'
                        return (
                        <li key={r.id} className="goal-results__item">
                          <button
                            type="button"
                            className="goal-results__btn"
                            onClick={() => {
                              if (!r.test_paper_id) return
                              if (isTaking) {
                                navigate(`/exam/taking/${r.test_paper_id}`)
                              } else {
                                navigate(`/exam/result/${r.test_paper_id}`)
                              }
                            }}
                          >
                            <span className="goal-results__head">
                              <span
                                className={`goal-results__tag goal-results__tag--${
                                  isTaking ? 'taking' : 'graded'
                                }`}
                              >
                                {isTaking ? '答题中' : r.title || '批改完成'}
                              </span>
                              <span className="goal-results__time">
                                {r.created_at
                                  ? String(r.created_at).slice(0, 16).replace('T', ' ')
                                  : ''}
                              </span>
                            </span>
                            <span className="goal-results__summary">
                              {r.summary ||
                                (r.earned_score != null
                                  ? `得分 ${r.earned_score}/${r.total_score ?? '-'}`
                                  : '')}
                            </span>
                          </button>
                        </li>
                        )
                      })}
                    </ul>
                  </div>
                  )
                })()}

                <div className="goal-card__actions">
                  <Button
                    type="primary"
                    size="small"
                    icon={<FormOutlined />}
                    onClick={() => startAssess(g)}
                  >
                    {g.mastery_status === 'assessed' ? '再次评测' : '开始评测'}
                  </Button>
                  <Button
                    size="small"
                    icon={<ApartmentOutlined />}
                    onClick={() => navigate(`/learning-map/${g.id}`)}
                  >
                    学习地图
                  </Button>
                  <Button
                    size="small"
                    icon={<CompassOutlined />}
                    onClick={() => navigate(`/goals/${g.id}/path`)}
                  >
                    学习路径
                  </Button>
                  {!g.is_primary && (
                    <Button size="small" icon={<StarOutlined />} onClick={() => setPrimary(g)}>
                      设为主目标
                    </Button>
                  )}
                  <Button size="small" icon={<EditOutlined />} onClick={() => navigate(`/goals/${g.id}/edit`)}>
                    编辑
                  </Button>
                  <Button size="small" icon={<CopyOutlined />} onClick={() => copy(g)}>
                    复制
                  </Button>
                  <Button size="small" icon={<InboxOutlined />} onClick={() => archive(g)}>
                    归档
                  </Button>
                </div>
              </div>
            </article>
          )
        })}
      </div>

      {goals.length > 0 && (
        <Typography.Paragraph type="secondary" style={{ marginTop: 20, marginBottom: 0 }}>
          可创建多个目标并切换主目标；后续测评将读取当前主目标。
        </Typography.Paragraph>
      )}
    </div>
  )
}

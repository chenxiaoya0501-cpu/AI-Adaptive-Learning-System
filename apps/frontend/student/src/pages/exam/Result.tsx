import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Progress, Spin, Tabs, Tag, Tooltip, Typography, message } from 'antd'
import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import {
  TYPE_LABELS,
  testsApi,
  type AbilityAssessment,
  type PaperResultDetail,
} from '../../api/tests'
import {
  ExamQuestionBody,
  RichQuestionContent,
} from '../../components/RichQuestionContent'
import './examTaking.css'

function apiError(e: any, fallback: string) {
  const d = e?.response?.data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map((x) => x.msg || JSON.stringify(x)).join('；')
  return fallback
}

function DistBars({
  rows,
  labelKey,
  countKey = 'wrong_count',
  knowledgeTooltip = false,
}: {
  rows: Array<Record<string, any>>
  labelKey: string
  countKey?: string
  knowledgeTooltip?: boolean
}) {
  const max = Math.max(1, ...rows.map((r) => Number(r[countKey] || 0)))
  if (!rows.length) {
    return <div className="assess-empty">暂无数据</div>
  }
  return (
    <ul className="assess-bars">
      {rows.map((r) => {
        const label = String(r[labelKey] ?? '')
        const count = Number(r[countKey] || 0)
        const rate = r.wrong_rate != null ? Math.round(Number(r.wrong_rate) * 100) : null
        const attempted = r.attempted != null ? Number(r.attempted) : null
        return (
          <li key={label} className="assess-bars__item">
            <Tooltip
              placement="right"
              color="#ffffff"
              overlayClassName="result-kp-tooltip"
              title={
                knowledgeTooltip ? (
                  <div className="assess-kp-tooltip">
                    <div className="assess-kp-tooltip__eyebrow">知识点</div>
                    <div className="assess-kp-tooltip__name">{label}</div>
                    <div className="assess-kp-tooltip__divider" />
                    <div className="assess-kp-tooltip__eyebrow">知识点描述</div>
                    <div className="assess-kp-tooltip__description">
                      {r.kp_description || '暂未录入知识点描述'}
                    </div>
                  </div>
                ) : null
              }
            >
              <div className="assess-bars__label">{label}</div>
            </Tooltip>
            <div className="assess-bars__track">
              <div
                className="assess-bars__fill"
                style={{ width: `${Math.round((count / max) * 100)}%` }}
              />
            </div>
            <div className="assess-bars__meta">
              {count} 题
              {attempted != null ? ` / ${attempted}` : ''}
              {rate != null ? ` · 错率 ${rate}%` : ''}
            </div>
          </li>
        )
      })}
    </ul>
  )
}

function AssessmentPanel({
  assessment,
  status,
}: {
  assessment?: AbilityAssessment | null
  status?: string | null
}) {
  if (status === 'failed' || assessment?.status === 'failed') {
    return (
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message="能力评估暂未生成"
        description={assessment?.error || '可刷新本页重试；不影响查看逐题批改结果。'}
      />
    )
  }
  if (!assessment || assessment.status === 'pending' || status === 'pending') {
    return (
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="能力评估生成中"
        description="批改完成后正在分析能力水平，请稍后刷新本页。"
      />
    )
  }

  const overall = assessment.overall
  const wrong = assessment.wrong_analysis
  const knowledgeItems = assessment.knowledge_items || []
  const history = overall?.progress?.history || []

  return (
    <section className="taking-main assess-panel" style={{ marginBottom: 16 }}>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        能力水平评估
      </Typography.Title>
      {assessment.llm_used ? (
        <div className="assess-hint">已结合大模型生成诊断叙述</div>
      ) : (
        <div className="assess-hint">基于作答统计与题库能力标注生成</div>
      )}

      <div className="assess-block">
        <Typography.Title level={5}>1. 整体分析</Typography.Title>
        <p className="assess-text">{overall?.summary || '暂无整体分析。'}</p>
        <div className="assess-tags">
          {(overall?.strengths || []).map((s) => (
            <Tag key={`s-${s}`} color="success">
              擅长 · {s}
            </Tag>
          ))}
          {(overall?.weaknesses || []).map((w) => (
            <Tag key={`w-${w}`} color="warning">
              欠缺 · {w}
            </Tag>
          ))}
        </div>
        <div className="assess-subcard">
          <div className="assess-subcard__title">与历史测试对比</div>
          <p className="assess-text" style={{ marginBottom: history.length ? 10 : 0 }}>
            {overall?.progress_comment || '暂无历史对比。'}
          </p>
          {history.length > 0 ? (
            <ul className="assess-history">
              {history.slice(0, 5).map((h) => (
                <li key={h.paper_id}>
                  <span>{h.title || `试卷 #${h.paper_id}`}</span>
                  <span>
                    {h.earned_score}/{h.total_score}（{h.rate}%）
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          {overall?.progress?.score_delta != null ? (
            <div style={{ marginTop: 8 }}>
              <Tag color={overall.progress.score_delta >= 0 ? 'green' : 'red'}>
                较上次 {overall.progress.score_delta >= 0 ? '+' : ''}
                {overall.progress.score_delta} 分
              </Tag>
            </div>
          ) : null}
        </div>
      </div>

      <div className="assess-block">
        <Typography.Title level={5}>2. 错题分析</Typography.Title>
        <p className="assess-text">{wrong?.qualitative || '暂无错题定性分析。'}</p>
        <div className="assess-grid">
          <div className="assess-subcard">
            <div className="assess-subcard__title">能力维度分布</div>
            <DistBars rows={wrong?.ability_distribution || []} labelKey="dimension" />
          </div>
          <div className="assess-subcard">
            <div className="assess-subcard__title">难易等级分布</div>
            <DistBars rows={wrong?.difficulty_distribution || []} labelKey="bucket" />
          </div>
          <div className="assess-subcard">
            <div className="assess-subcard__title">知识点分布</div>
            <DistBars
              rows={wrong?.knowledge_distribution || []}
              labelKey="kp_name"
              knowledgeTooltip
            />
          </div>
          <div className="assess-subcard">
            <div className="assess-subcard__title">知识点类别分布</div>
            <DistBars rows={wrong?.category_distribution || []} labelKey="category_1" />
          </div>
        </div>
      </div>

      <div className="assess-block">
        <Typography.Title level={5}>3. 知识点分析（逐题）</Typography.Title>
        {knowledgeItems.length === 0 ? (
          <Alert type="success" showIcon message="本次无判定错误的题目，掌握较好。" />
        ) : (
          <ul className="assess-kp-list">
            {knowledgeItems.map((item) => (
              <li key={item.question_id}>
                <div className="assess-kp-list__head">
                  <strong>
                    第 {item.seq} 题
                    {item.kp_name ? ` · ${item.kp_name}` : ''}
                  </strong>
                  <span>
                    {item.score_got ?? 0}/{item.score ?? 0} 分
                  </span>
                </div>
                <div className="assess-kp-list__meta">
                  {item.ability_dimension ? (
                    <Tag>能力 · {item.ability_dimension}</Tag>
                  ) : null}
                  {item.difficulty_bucket ? (
                    <Tag>难度 · {item.difficulty_bucket}</Tag>
                  ) : null}
                  {item.ability_gap ? <Tag color="orange">缺陷 · {item.ability_gap}</Tag> : null}
                  {(item.error_links || []).map((link) => (
                    <Tag key={`${item.seq}-${link}`}>{link}</Tag>
                  ))}
                </div>
                <p className="assess-text" style={{ marginBottom: 0 }}>
                  {item.reason || '暂无逐题原因分析。'}
                </p>
                {item.content_preview ? (
                  <div className="assess-kp-list__preview">{item.content_preview}</div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>

      {(assessment.ability_overview || []).length > 0 ? (
        <div className="assess-block">
          <Typography.Title level={5}>能力维度正确率概览</Typography.Title>
          <div className="assess-overview">
            {(assessment.ability_overview || []).map((row) => (
              <div key={row.dimension} className="assess-overview__item">
                <div className="assess-overview__label">{row.dimension}</div>
                <Progress
                  percent={Math.round((row.accuracy || 0) * 100)}
                  size="small"
                  strokeColor="#0f766e"
                />
                <div className="assess-overview__meta">
                  对 {row.correct}/{row.attempted} · 错 {row.wrong}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  )
}

export default function Result() {
  const { paperId: paperIdParam } = useParams()
  const paperId = Number(paperIdParam)
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<PaperResultDetail | null>(null)

  const load = useCallback(async () => {
    if (!paperId) return
    setLoading(true)
    try {
      const { data: res } = await testsApi.result(paperId)
      setData(res)
    } catch (e: any) {
      message.error(apiError(e, '加载批改结果失败'))
    } finally {
      setLoading(false)
    }
  }, [paperId])

  useEffect(() => {
    load()
  }, [load])

  if (loading) {
    return (
      <div className="taking-page taking-page--center">
        <Spin tip="加载批改结果…" />
      </div>
    )
  }

  if (!data) {
    return (
      <div className="taking-page">
        <Alert
          type="error"
          showIcon
          message="暂无批改结果"
          action={
            <Button size="small" onClick={() => navigate('/goals')}>
              返回目标
            </Button>
          }
        />
      </div>
    )
  }

  const rate =
    data.total_score > 0 ? Math.round(((data.earned_score || 0) / data.total_score) * 100) : 0
  const pendingCount = data.items.filter((x) => x.is_correct == null).length

  return (
    <div className="taking-page">
      <Button
        type="link"
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate(`/goals`)}
        style={{ paddingLeft: 0, marginBottom: 8 }}
      >
        返回学习目标
      </Button>

      <section className="taking-main" style={{ marginBottom: 16 }}>
        <Typography.Title level={3} style={{ marginTop: 0 }}>
          {data.title || `试卷 #${data.paper_id}`} · 批改结果
        </Typography.Title>
        <Alert
          type="success"
          showIcon
          style={{ marginBottom: 12 }}
          message={`得分 ${data.earned_score ?? 0} / ${data.total_score}（${rate}%）`}
          description={`答对 ${data.correct_count}/${data.total_count} 题 · 作答 ${data.answered_count}/${data.total_count} 题${
            pendingCount ? ` · ${pendingCount} 题暂无法自动判分` : ''
          }`}
        />
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <Button type="primary" onClick={() => navigate(`/exam/taking/${data.paper_id}`)}>
            查看作答
          </Button>
          <Button onClick={() => navigate(`/exam?goalId=${data.goal_id}&paperId=${data.paper_id}`)}>
            返回试卷预览
          </Button>
          <Button onClick={() => navigate('/goals')}>查看目标结果记录</Button>
          <Button onClick={() => void load()}>刷新评估</Button>
        </div>
      </section>

      <Tabs
        className="result-tabs"
        defaultActiveKey="grading"
        items={[
          {
            key: 'grading',
            label: '批改反馈',
            children: (
              <section className="taking-main result-tab-panel">
                <Alert
                  type="info"
                  showIcon
                  className="result-grading-note"
                  message="批改依据"
                  description="参照组卷时从题库快照的「答案」字段自动比对。选择题比选项；填空比文本；解答题仅在参考答案含可比对文本时判分。参考答案若主要为公式图片，当前版本不计分，仅展示参考内容。"
                />
                <Typography.Title level={5}>逐题反馈</Typography.Title>
                <ul className="exam-q-list" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                  {data.items.map((item) => {
                    const tone =
                      item.is_correct === true
                        ? '#f3faf8'
                        : item.is_correct === false
                          ? '#fff8f6'
                          : '#f8fafc'
                    return (
                      <li
                        key={item.question_id}
                        style={{
                          padding: '14px 16px',
                          borderRadius: 12,
                          border: '1px solid rgba(15, 118, 110, 0.12)',
                          marginBottom: 12,
                          background: tone,
                        }}
                      >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <strong>
                      第 {item.seq} 题 · {TYPE_LABELS[item.question_type] || item.question_type} ·{' '}
                      {item.score} 分
                    </strong>
                    <div style={{ marginTop: 6, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      {item.ability_dimension ? (
                        <Tag>{item.ability_dimension}</Tag>
                      ) : null}
                      {item.difficulty != null ? <Tag>难度 {item.difficulty}</Tag> : null}
                    </div>
                    {item.source_label ? (
                      <div style={{ marginTop: 6, fontSize: 13, color: '#0f766e', fontWeight: 600 }}>
                        题目来源：{item.source_label}
                      </div>
                    ) : null}

                    <div style={{ marginTop: 12 }}>
                      <div style={{ fontSize: 13, color: '#6b8587', marginBottom: 6 }}>原题目</div>
                      <div
                        style={{
                          padding: '10px 12px',
                          borderRadius: 10,
                          background: '#fff',
                          border: '1px solid rgba(15, 61, 62, 0.08)',
                        }}
                      >
                        {item.content ? (
                          <ExamQuestionBody
                            content={item.content}
                            options={item.options}
                            paperId={item.source_exam_paper_id}
                          />
                        ) : (
                          <span style={{ color: '#6b8587' }}>（无题干快照）</span>
                        )}
                      </div>
                    </div>

                    <div style={{ marginTop: 12, fontSize: 13, color: '#3d5a5c' }}>
                      <div style={{ marginBottom: 4, color: '#6b8587' }}>你的作答</div>
                      {item.question_type === 'choice' ? (
                        <span>{item.selected_option || '未作答'}</span>
                      ) : (
                        <span style={{ whiteSpace: 'pre-wrap' }}>
                          {item.answer_text || '未作答'}
                        </span>
                      )}
                    </div>

                    <div style={{ marginTop: 12, fontSize: 13, color: '#3d5a5c' }}>
                      <div style={{ marginBottom: 4, color: '#6b8587' }}>参考答案</div>
                      {item.correct_answer ? (
                        <RichQuestionContent
                          text={item.correct_answer}
                          paperId={item.source_exam_paper_id}
                        />
                      ) : (
                        <span style={{ color: '#6b8587' }}>（题库未录入文本/图片答案）</span>
                      )}
                    </div>

                    <div style={{ marginTop: 12, fontSize: 13, color: '#3d5a5c' }}>
                      <div style={{ marginBottom: 4, color: '#6b8587' }}>答案解析</div>
                      {item.analysis ? (
                        <div
                          style={{
                            padding: '10px 12px',
                            borderRadius: 10,
                            background: '#fff',
                            border: '1px solid rgba(15, 61, 62, 0.08)',
                          }}
                        >
                          <RichQuestionContent
                            text={item.analysis}
                            paperId={item.source_exam_paper_id}
                          />
                        </div>
                      ) : (
                        <span style={{ color: '#6b8587' }}>（暂无解析）</span>
                      )}
                    </div>

                    {item.grading_note ? (
                      <div style={{ marginTop: 8, fontSize: 12, color: '#6b8587' }}>
                        判分说明：{item.grading_note}
                      </div>
                    ) : null}
                  </div>
                  <div style={{ textAlign: 'right', flexShrink: 0 }}>
                    {item.is_correct === true ? (
                      <Tag icon={<CheckCircleOutlined />} color="success">
                        正确
                      </Tag>
                    ) : item.is_correct === false ? (
                      <Tag icon={<CloseCircleOutlined />} color="error">
                        错误
                      </Tag>
                    ) : (
                      <Tag icon={<QuestionCircleOutlined />} color="default">
                        待核验
                      </Tag>
                    )}
                    <div style={{ marginTop: 8, fontWeight: 650, color: '#14363a' }}>
                      {item.score_got ?? 0} / {item.score} 分
                    </div>
                  </div>
                </div>
                      </li>
                    )
                  })}
                </ul>
              </section>
            ),
          },
          {
            key: 'assessment',
            label: '能力水平评估',
            children: (
              <AssessmentPanel
                assessment={data.assessment}
                status={data.assessment_status}
              />
            ),
          },
        ]}
      />
    </div>
  )
}

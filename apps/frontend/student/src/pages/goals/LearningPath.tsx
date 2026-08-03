import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Drawer,
  Empty,
  InputNumber,
  Progress,
  Skeleton,
  Space,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CompassOutlined,
  HistoryOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { goalsApi, type LearningGoal } from '../../api/goals'
import {
  learningPathsApi,
  type LearningPath as LearningPathData,
  type LearningPathNode,
  type LearningPathTask,
} from '../../api/learningPaths'
import './learningPath.css'

const ROLE_LABEL: Record<string, string> = {
  prerequisite: '前置基础',
  verify: '先行验证',
  remediate: '重点补弱',
  strengthen: '首轮巩固',
  review: '复习保持',
}

function errorText(error: any) {
  return error?.response?.data?.detail || '学习路径操作失败'
}

function firstRoundNodeGain(node: LearningPathNode) {
  if (node.reason.base_direct_gain != null) return Number(node.reason.base_direct_gain)
  return Math.max(
    0,
    Number(node.expected_gain || 0) - Number(node.reason.reinforcement_gain || 0),
  )
}

function firstRoundNodeOptimisticGain(node: LearningPathNode) {
  const reinforcementOptimistic = (node.reason.reinforcement_blocks || []).reduce(
    (sum, block) => sum + Number(block.optimistic_gain || 0),
    0,
  )
  return Math.max(
    0,
    Number(node.reason.optimistic_gain ?? node.expected_gain ?? 0) - reinforcementOptimistic,
  )
}

function firstRoundNodeMinutes(node: LearningPathNode) {
  return Math.max(
    0,
    Number(node.estimated_minutes || 0) - Number(node.reason.reinforcement_minutes || 0),
  )
}

function taskButton(task: LearningPathTask) {
  if (task.status === 'blocked') return '等待前置'
  if (task.status === 'pending') return '开始'
  if (task.status === 'in_progress') return task.task_type === 'checkpoint' ? '完成检查' : '完成'
  if (task.status === 'completed') return '已完成'
  return '已跳过'
}

export default function LearningPath() {
  const { goalId } = useParams()
  const goalIdNumber = Number(goalId)
  const navigate = useNavigate()
  const [goal, setGoal] = useState<LearningGoal | null>(null)
  const [path, setPath] = useState<LearningPathData | null>(null)
  const [currentPath, setCurrentPath] = useState<LearningPathData | null>(null)
  const [versions, setVersions] = useState<LearningPathData[]>([])
  const [historyOpen, setHistoryOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [taskLoading, setTaskLoading] = useState<number | null>(null)
  const [dailyMinutes, setDailyMinutes] = useState(45)

  const load = useCallback(async () => {
    if (!Number.isFinite(goalIdNumber)) return
    setLoading(true)
    try {
      const [goalResult, pathResult] = await Promise.all([
        goalsApi.get(goalIdNumber),
        learningPathsApi.current(goalIdNumber),
      ])
      setGoal(goalResult.data)
      if (pathResult.data) {
        setDailyMinutes(
          pathResult.data.summary.daily_study_minutes
          || goalResult.data.daily_study_minutes
          || 45,
        )
        setCurrentPath(pathResult.data)
        setPath(pathResult.data)
      } else {
        setDailyMinutes(goalResult.data.daily_study_minutes || 45)
        const preview = await learningPathsApi.preview(goalIdNumber, {
          daily_study_minutes: goalResult.data.daily_study_minutes || 45,
        })
        setPath(preview.data)
      }
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setLoading(false)
    }
  }, [goalIdNumber])

  useEffect(() => {
    void load()
  }, [load])

  const previewLatest = async () => {
    setGenerating(true)
    try {
      const result = await learningPathsApi.preview(goalIdNumber, {
        daily_study_minutes: dailyMinutes,
        generation_reason: currentPath ? 'manual_replan' : 'manual',
      })
      setPath(result.data)
      message.success('已按最新认知状态生成预览，确认后才会替换当前路径')
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setGenerating(false)
    }
  }

  const adoptPreview = async () => {
    setGenerating(true)
    try {
      const result = currentPath
        ? await learningPathsApi.replan(goalIdNumber, {
            daily_study_minutes: dailyMinutes,
            generation_reason: 'manual_replan',
          })
        : await learningPathsApi.generate(goalIdNumber, {
            daily_study_minutes: dailyMinutes,
            generation_reason: 'manual',
          })
      const active = await learningPathsApi.activate(result.data.id!)
      setCurrentPath(active.data)
      setPath(active.data)
      message.success('新路径已采用，旧版本已保留在历史记录中')
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setGenerating(false)
    }
  }

  const openHistory = async () => {
    try {
      const result = await learningPathsApi.versions(goalIdNumber)
      setVersions(result.data)
      setHistoryOpen(true)
    } catch (error) {
      message.error(errorText(error))
    }
  }

  const updateTask = async (task: LearningPathTask) => {
    if (!task.id || ['blocked', 'completed', 'skipped'].includes(task.status)) return
    setTaskLoading(task.id)
    try {
      const nextStatus = task.status === 'pending' ? 'in_progress' : 'completed'
      const result = await learningPathsApi.updateTask(task.id, { status: nextStatus })
      setCurrentPath(result.data)
      setPath(result.data)
      if (nextStatus === 'completed') message.success('任务已完成，后续可执行任务已自动解锁')
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setTaskLoading(null)
    }
  }

  const firstRoundNodes = useMemo(
    () => (path?.nodes || []).filter((node) => node.role !== 'verify'),
    [path],
  )

  const stages = useMemo(() => {
    const grouped = new Map<number, LearningPathNode[]>()
    firstRoundNodes.forEach((node) => {
      grouped.set(node.stage_index, [...(grouped.get(node.stage_index) || []), node])
    })
    return [...grouped.entries()]
      .sort(([a], [b]) => a - b)
      .map(([stageIndex, nodes]) => [
        stageIndex,
        [...nodes].sort((a, b) => a.order_index - b.order_index),
      ] as const)
  }, [firstRoundNodes])

  const firstRoundTasks = useMemo(
    () => {
      const firstRoundKnowledgeIds = new Set(firstRoundNodes.map((node) => node.kp_id))
      return (path?.tasks || []).filter(
        (task) => task.task_type !== 'reinforcement' && firstRoundKnowledgeIds.has(task.kp_id),
      )
    },
    [firstRoundNodes, path],
  )

  const tasksByDate = useMemo(() => {
    const grouped = new Map<string, LearningPathTask[]>()
    firstRoundTasks.forEach((task) => {
      grouped.set(task.scheduled_date, [...(grouped.get(task.scheduled_date) || []), task])
    })
    return [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [firstRoundTasks])

  const firstRoundStats = useMemo(() => {
    const nodes = firstRoundNodes
    const gainLow = nodes.reduce((sum, node) => sum + firstRoundNodeGain(node), 0)
    const gainHigh = nodes.reduce((sum, node) => sum + firstRoundNodeOptimisticGain(node), 0)
    const minutes = nodes.reduce((sum, node) => sum + firstRoundNodeMinutes(node), 0)
    const completionDate = path?.summary.first_round_completion_date
      || firstRoundTasks.reduce(
        (latest, task) => task.scheduled_date > latest ? task.scheduled_date : latest,
        '',
      )
    const completedTasks = firstRoundTasks.filter((task) => task.status === 'completed').length
    return {
      gainLow: Math.round(gainLow * 10) / 10,
      gainHigh: Math.round(gainHigh * 10) / 10,
      minutes,
      completionDate,
      completedTasks,
      taskCount: firstRoundTasks.length,
    }
  }, [firstRoundNodes, firstRoundTasks, path])

  if (loading) return <Skeleton active paragraph={{ rows: 10 }} />

  const showingHistory = Boolean(path?.id && currentPath?.id && path.id !== currentPath.id)
  const isPreview = path?.status === 'preview'
  const dailyMinutesPending = Boolean(
    path && dailyMinutes !== path.summary.daily_study_minutes,
  )
  const firstRoundScoreLow = Math.round(
    ((path?.summary.current_score || 0) + firstRoundStats.gainLow) * 10,
  ) / 10
  const firstRoundScoreHigh = Math.round(
    ((path?.summary.current_score || 0) + firstRoundStats.gainHigh) * 10,
  ) / 10
  const missingEvidenceCount = path?.summary.insufficient_mastery_evidence_count
    ?? path?.summary.deferred_nodes?.filter(
      (node) => node.reason === 'insufficient_evidence_next_round',
    ).length
    ?? 0
  const capacityDeferredCount = path?.summary.deferred_nodes?.filter(
    (node) => node.reason === 'capacity_insufficient',
  ).length || 0
  const firstRoundCompletionDate = firstRoundStats.completionDate
  const firstRoundGainText = firstRoundStats.gainHigh > firstRoundStats.gainLow
    ? `+${firstRoundStats.gainLow}～${firstRoundStats.gainHigh}`
    : `+${firstRoundStats.gainLow}`
  const firstRoundScoreText = firstRoundScoreHigh > firstRoundScoreLow
    ? `${firstRoundScoreLow}～${firstRoundScoreHigh}`
    : `${firstRoundScoreLow}`
  const firstRoundNotice = `${firstRoundCompletionDate
    ? `按当前排期，预计于 ${firstRoundCompletionDate} 完成首轮目标；`
    : '当前尚没有可进入首轮的正式学习任务；'}`
    + `本轮预计提分 ${firstRoundGainText}，预计综合分约 ${firstRoundScoreText} 分。`
    + '本轮提分只统计已有充分测评证据知识点的首次学习收益，不计入尚未验证的后续强化收益，后继解锁价值和诊断信息价值也不作为分数。'
    + `${missingEvidenceCount
      ? `当前另有 ${missingEvidenceCount} 个目标相关知识点因掌握情况数据不足，留待下一轮判断。`
      : ''}`
    + '完成本轮掌握检查和首轮复测、形成足够的有效作答数据后，系统才会生成下一轮规划，并重新判断证据不足知识点及是否需要强化。'
    + `${capacityDeferredCount
      ? `受当前每日 ${path?.summary.daily_study_minutes || dailyMinutes} 分钟和学习截止日期限制，仍有 ${capacityDeferredCount} 个有价值知识点未能排入首轮；建议增加每日投入或延长学习周期。`
      : ''}`
  const displayWarnings = (path?.summary.warnings || []).filter(
    (warning) => !(
      warning.includes('目标不可达')
      || warning.includes('强化')
      || warning.includes('掌握证据')
      || warning.includes('有效作答数据')
    ),
  )

  return (
    <div className="learning-path-page">
      <button className="path-back" onClick={() => navigate('/goals')} type="button">
        <ArrowLeftOutlined /> 返回学习目标
      </button>
      <header className="path-header">
        <div>
          <Typography.Title level={2}>{goal?.title || '学习目标'} · 学习路径</Typography.Title>
          <Typography.Text type="secondary">基于当前认知状态、考试价值和前后置关系生成首轮规划</Typography.Text>
        </div>
        <Space wrap>
          <span className="daily-setting">
            每天
            <InputNumber min={15} max={720} value={dailyMinutes} onChange={(value) => setDailyMinutes(value || 45)} />
            分钟
            {dailyMinutesPending && <Tag color="orange">尚未应用</Tag>}
          </span>
          <Button icon={<HistoryOutlined />} onClick={openHistory}>历史版本</Button>
          <Button icon={<ReloadOutlined />} loading={generating} onClick={previewLatest}>
            {dailyMinutesPending
              ? `预览 ${dailyMinutes} 分钟方案`
              : currentPath
                ? '按最新状态预览'
                : '重新预览'}
          </Button>
          {isPreview && (
            <Button type="primary" icon={<CompassOutlined />} loading={generating} onClick={adoptPreview}>
              采用此路径
            </Button>
          )}
        </Space>
      </header>

      {showingHistory && (
        <Alert
          type="info"
          showIcon
          message={`正在查看历史版本 v${path?.version}`}
          action={<Button size="small" onClick={() => setPath(currentPath)}>返回当前版本</Button>}
        />
      )}
      {currentPath?.summary.is_stale && !isPreview && (
        <Alert
          type="warning"
          showIcon
          message="认知状态或学习目标已经更新"
          description="当前路径仍可继续执行，但建议先预览新版本；系统不会自动覆盖正在执行的路径。"
          action={<Button size="small" type="primary" onClick={previewLatest}>预览新路径</Button>}
        />
      )}
      {isPreview && (
        <Alert
          type="info"
          showIcon
          message="这是路径预览"
          description="预览不会写入任务；点击“采用此路径”后才会保存并归档旧版本。"
        />
      )}

      {path && (
        <Alert
          type="warning"
          showIcon
          message="这是首轮学习规划"
          description={firstRoundNotice}
        />
      )}

      {!path || !firstRoundNodes.length ? (
        <Empty description="当前没有具备充分掌握证据且适合进入首轮学习的知识点">
          <Button type="primary" onClick={() => navigate(`/exam?goalId=${goalIdNumber}`)}>去完成一次测评</Button>
        </Empty>
      ) : (
        <>
          {!!displayWarnings.length && (
            <Alert type="warning" showIcon message={displayWarnings.join('；')} />
          )}
          <section className="path-overview">
            <div><strong>{path.summary.current_score}</strong><span>综合估分</span></div>
            <div><strong>{path.summary.target_score}</strong><span>目标分</span></div>
            <div>
              <strong>
                {firstRoundGainText}
              </strong>
              <span title="所有阶段内各知识点首轮预计提分的总和；不包含强化、后继解锁价值和诊断信息价值">
                首轮预计提分总和
              </span>
            </div>
            <div><strong>{firstRoundNodes.length}</strong><span>首轮规划知识点</span></div>
            <div><strong>{Math.ceil(firstRoundStats.minutes / 60)}h</strong><span>首轮有效学习量</span></div>
          </section>

          <div className="path-content">
            <main className="path-timeline">
              {stages.map(([stageIndex, nodes]) => {
                const secondaryCategory = String(nodes[0]?.reason.category_2 || '').trim()
                const primaryCategory = String(nodes[0]?.reason.category_1 || '').trim()
                const theme = (
                  secondaryCategory
                  || primaryCategory
                  || String(nodes[0]?.reason.stage_theme || '个性化学习')
                    .replace(/^未设置二级分类\s*[·・]\s*/, '')
                ).replace(/^[（(]\s*\d+\s*[）)]\s*/, '')
                const categoryLevelLabel = secondaryCategory ? '二级分类' : '一级分类'
                const stageMinutes = nodes.reduce(
                  (sum, node) => sum + firstRoundNodeMinutes(node),
                  0,
                )
                const stageStrategicValue = nodes.reduce((sum, node) => {
                  return sum
                    + firstRoundNodeGain(node)
                    + 0.70 * Number(node.reason.unlock_gain || 0)
                }, 0)
                const stageMarginalValue = stageStrategicValue / Math.max(stageMinutes, 1)
                const stageExpectedGain = nodes.reduce(
                  (sum, node) => sum + firstRoundNodeGain(node),
                  0,
                )
                const stageOptimisticGain = nodes.reduce(
                  (sum, node) => sum + firstRoundNodeOptimisticGain(node),
                  0,
                )
                return (
                  <section className="path-stage" key={stageIndex}>
                    <div className="stage-marker"><small>阶段</small><strong>{stageIndex}</strong></div>
                    <div className="stage-body">
                      <div className="stage-title">
                        <div>
                          <Typography.Title level={4}>{theme}</Typography.Title>
                          <Typography.Text type="secondary">
                            同一{categoryLevelLabel} · 满足前置关系后按阶段边际价值降序 · {nodes.length} 个知识点
                          </Typography.Text>
                        </div>
                        <div className="stage-metrics">
                          <span title="本阶段所有知识点首轮预计提分相加；保守值～乐观值">
                            <small>阶段首轮预计提分</small>
                            <strong>
                              +{stageExpectedGain.toFixed(1)}
                              {stageOptimisticGain > stageExpectedGain
                                ? `～${stageOptimisticGain.toFixed(1)}`
                                : ''}
                            </strong>
                          </span>
                          <span title="首轮直接预计提分 + 0.7 × 后继解锁预计收益">
                            <small>战略价值合计</small>
                            <strong>{stageStrategicValue.toFixed(2)}</strong>
                          </span>
                          <span title="阶段战略价值合计 ÷ 阶段首轮总时间">
                            <small>阶段边际价值</small>
                            <strong>{stageMarginalValue.toFixed(4)}/分钟</strong>
                          </span>
                          <Tag>{stageMinutes} 分钟</Tag>
                        </div>
                      </div>
                      <div className="path-node-list">
                        {nodes.map((node) => {
                          const baseTarget = Number(node.reason.base_target_mastery || node.target_mastery)
                          const firstPassMinutes = firstRoundNodeMinutes(node)
                          const firstPassSummary = String(node.reason.summary || '')
                          const knowledgeTheme = String(node.reason.knowledge_theme || '')
                          const firstPassGain = firstRoundNodeGain(node)
                          const firstPassOptimisticGain = firstRoundNodeOptimisticGain(node)
                          return (
                            <article className={`path-node path-node--${node.role}`} key={node.kp_id}>
                            <div className="node-order" title="知识点首次学习优先级">
                              <small>优先</small>
                              <strong>{node.order_index}</strong>
                            </div>
                            <div className="node-main">
                              <div className="node-title-row">
                                <strong>{node.name}</strong>
                                <div className="node-title-tags">
                                  {knowledgeTheme && <Tag color="cyan">{knowledgeTheme}</Tag>}
                                  <Tag>{ROLE_LABEL[node.role] || node.role}</Tag>
                                </div>
                              </div>
                              <p>{firstPassSummary}</p>
                              <div className="node-progress">
                                <span>{node.current_mastery == null ? '待验证' : `${Math.round(node.current_mastery)} 分`}</span>
                                <Progress
                                  percent={Math.round(baseTarget)}
                                  success={{ percent: node.current_mastery == null ? 0 : Math.round(node.current_mastery) }}
                                  showInfo={false}
                                />
                                <span>首轮目标 {Math.round(baseTarget)}</span>
                              </div>
                            </div>
                            <div className="node-value">
                              {firstPassGain > 0 && (
                                <span title="仅计算该知识点本轮首次学习的预计提分">
                                  首轮预计提分 +{firstPassGain.toFixed(1)}
                                  {firstPassOptimisticGain > firstPassGain
                                    ? `～${firstPassOptimisticGain.toFixed(1)}`
                                    : ''}
                                </span>
                              )}
                              {Number(node.reason.unlock_gain || 0) > 0 && <span>后继解锁价值 {Number(node.reason.unlock_gain).toFixed(1)}</span>}
                            </div>
                            <div className="node-meta">
                              <span className="node-meta-time">
                                <ClockCircleOutlined /> 首轮 {firstPassMinutes} 分钟
                              </span>
                              <span className="node-meta-role">
                                {node.status === 'completed' ? '已完成' : ROLE_LABEL[node.role]}
                              </span>
                              {!isPreview && path.id && (
                                <Button
                                  className="node-learn-button"
                                  type="link"
                                  size="small"
                                  icon={<PlayCircleOutlined />}
                                  onClick={() => navigate(`/learn/${path.id}/${encodeURIComponent(node.kp_id)}`)}
                                >
                                  {node.status === 'completed' ? '再次学习' : '开始学习'}
                                </Button>
                              )}
                            </div>
                          </article>
                          )
                        })}
                      </div>
                    </div>
                  </section>
                )
              })}
            </main>

            <aside className="path-side">
              <section className="path-plan-card">
                <h3><CheckCircleOutlined /> 执行计划</h3>
                <Progress percent={path.summary.progress_percent || 0} strokeColor="#69c9ba" />
                <dl>
                  <div><dt>首轮预计分数</dt><dd>{firstRoundScoreText}</dd></div>
                  <div><dt>首轮完成日期</dt><dd>{firstRoundCompletionDate || '-'}</dd></div>
                  <div><dt>每日投入</dt><dd>{path.summary.daily_study_minutes} 分钟</dd></div>
                  <div><dt>首轮剩余容量</dt><dd>{Math.max(0, Number(path.summary.capacity_minutes || 0) - firstRoundStats.minutes)} 分钟</dd></div>
                  <div><dt>首轮学习任务</dt><dd>{firstRoundStats.completedTasks}/{firstRoundStats.taskCount}</dd></div>
                  <div><dt>路径版本</dt><dd>v{path.version || '预览'}</dd></div>
                </dl>
                {!isPreview && path.status === 'current' && (
                  <Button block icon={<PlayCircleOutlined />} onClick={() => navigate(`/exam?goalId=${goalIdNumber}`)}>
                    完成首轮后去复测
                  </Button>
                )}
              </section>

              <section className="path-task-card">
                <h3>任务时间线</h3>
                {tasksByDate.map(([taskDate, tasks]) => (
                  <div className="task-day" key={taskDate}>
                    <h4>{taskDate}</h4>
                    {tasks.map((task) => (
                        <div
                          className={`path-task path-task--${task.status} path-task--${task.task_type}`}
                          key={task.id || task.sequence}
                        >
                          <div>
                            <strong>{task.title}</strong>
                            <span>
                              执行步骤 {task.sequence} · {task.estimated_minutes} 分钟
                            </span>
                          </div>
                          {!isPreview && path.status === 'current' ? (
                            <Button
                              size="small"
                              disabled={['blocked', 'completed', 'skipped'].includes(task.status)}
                              loading={taskLoading === task.id}
                              onClick={() => updateTask(task)}
                            >
                              {taskButton(task)}
                            </Button>
                          ) : (
                            <Tag>{taskButton(task)}</Tag>
                          )}
                        </div>
                    ))}
                  </div>
                ))}
              </section>
            </aside>
          </div>
        </>
      )}

      <Drawer title="学习路径历史版本" open={historyOpen} onClose={() => setHistoryOpen(false)} width={440}>
        <div className="path-history-list">
          {versions.map((item) => (
            <button
              type="button"
              className={`path-history-item ${item.id === currentPath?.id ? 'is-current' : ''}`}
              key={item.id}
              onClick={() => {
                setPath(item)
                setHistoryOpen(false)
              }}
            >
              <span><strong>v{item.version}</strong><Tag>{item.status === 'current' ? '当前' : '已归档'}</Tag></span>
              <span>
                首轮预计提升 {
                  Math.round(
                    (item.nodes || []).reduce(
                      (sum, node) => sum + firstRoundNodeGain(node),
                      0,
                    ) * 10,
                  ) / 10
                } 分 · {(item.nodes || []).filter((node) => node.role !== 'verify').length} 个知识点
              </span>
              <small>{item.created_at?.slice(0, 16).replace('T', ' ')}</small>
            </button>
          ))}
          {!versions.length && <Empty description="暂无历史版本" />}
        </div>
      </Drawer>
    </div>
  )
}

import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Empty,
  Input,
  List,
  Progress,
  Radio,
  Skeleton,
  Space,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  ArrowLeftOutlined,
  BookOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  LinkOutlined,
  PlayCircleOutlined,
  SyncOutlined,
} from '@ant-design/icons'
import { Link as RouterLink, useNavigate, useParams } from 'react-router-dom'
import {
  coursesApi,
  type Course,
  type CourseSummary,
  type MasteryEvaluation,
  type MasterySyncInfo,
} from '../../api/courses'
import {
  learningPathsApi,
  type LearningPath,
  type LearningPathNode,
} from '../../api/learningPaths'
import { RichQuestionContent } from '../../components/RichQuestionContent'
import { ExplanationBlocks } from '../../components/ExplanationBlocks'
import { CourseTutorPanel } from './CourseTutorPanel'
import './learn.css'

const { Title, Paragraph, Text } = Typography

function errorText(error: any) {
  return error?.response?.data?.detail || '课程加载失败，请稍后重试'
}

function cleanStageTitle(value: unknown) {
  return String(value || '个性化学习')
    .replace(/^未设置二级分类\s*[·・]\s*/, '')
    .replace(/^[（(]\s*\d+\s*[）)]\s*/, '')
}

const ROLE_LABEL: Record<string, string> = {
  prerequisite: '前置基础',
  remediate: '重点补弱',
  strengthen: '首轮巩固',
  review: '复习保持',
}

function PathCatalog({
  path,
  currentKpId,
}: {
  path: LearningPath
  currentKpId: string
}) {
  const nodes = useMemo(
    () => [...path.nodes]
      .filter((node) => node.role !== 'verify')
      .sort((a, b) => a.order_index - b.order_index),
    [path.nodes],
  )
  const stages = useMemo(() => {
    const grouped = new Map<number, LearningPathNode[]>()
    nodes.forEach((node) => {
      const members = grouped.get(node.stage_index) || []
      members.push(node)
      grouped.set(node.stage_index, members)
    })
    return [...grouped.entries()].sort(([left], [right]) => left - right)
  }, [nodes])

  return (
    <aside className="course-catalog" aria-label="本期学习路径目录">
      <RouterLink className="course-path-back" to={`/goals/${path.goal_id}/path`}>
        <ArrowLeftOutlined /> 返回学习路径
      </RouterLink>
      <div className="course-catalog-header">
        <Text strong>本期学习目录</Text>
      </div>
      <nav className="course-catalog-tree">
        <ol className="course-catalog-stages">
          {stages.map(([stageIndex, stageNodes]) => {
            const firstNode = stageNodes[0]
            const stageTitle = cleanStageTitle(
              firstNode.reason.category_2
              || firstNode.reason.category_1
              || firstNode.reason.stage_theme,
            )
            return (
              <li className="course-catalog-stage" key={`${path.id}-${stageIndex}`}>
                <div className="course-catalog-stage-title">
                  <span>{stageIndex}</span>
                  <strong>{stageTitle}</strong>
                </div>
                <ul>
                  {stageNodes.map((node) => {
                    const isCurrent = node.kp_id === currentKpId
                    return (
                      <li key={node.kp_id}>
                        <RouterLink
                          aria-current={isCurrent ? 'page' : undefined}
                          className={isCurrent ? 'is-current' : ''}
                          to={`/learn/${path.id}/${encodeURIComponent(node.kp_id)}`}
                        >
                          {node.name}
                        </RouterLink>
                      </li>
                    )
                  })}
                </ul>
              </li>
            )
          })}
        </ol>
      </nav>
    </aside>
  )
}

function CourseList() {
  const navigate = useNavigate()
  const [items, setItems] = useState<CourseSummary[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    coursesApi.list().then(setItems).catch((error) => message.error(errorText(error))).finally(() => setLoading(false))
  }, [])

  if (loading) return <Skeleton active />
  const completed = items.filter((item) => item.status === 'completed').length
  return (
    <div className="learn-home">
      <div className="learn-heading">
        <div><Title level={2}>课程学习</Title><Text type="secondary">按照当前学习路径，逐个完成讲解与针对性练习</Text></div>
        <Progress type="circle" size={72} percent={items.length ? Math.round(completed / items.length * 100) : 0} />
      </div>
      {!items.length ? (
        <Empty description="暂无可学习课程">
          <Button type="primary" onClick={() => navigate('/goals')}>先生成学习路径</Button>
        </Empty>
      ) : (
        <List
          grid={{ gutter: 16, column: 2, xs: 1, sm: 1, md: 2 }}
          dataSource={items}
          renderItem={(item) => (
            <List.Item>
              <Card className={`course-summary ${item.status === 'completed' ? 'is-completed' : ''}`}>
                <Space direction="vertical" size={10} style={{ width: '100%' }}>
                  <Space wrap>
                    <Tag color="cyan">阶段 {item.stage_index}</Tag>
                    <Tag>{item.goal_title}</Tag>
                    {item.status === 'completed' && <Tag color="success">已完成</Tag>}
                  </Space>
                  <Title level={4}>{item.kp_name}</Title>
                  <Text type="secondary"><ClockCircleOutlined /> 预计 {item.estimated_minutes} 分钟</Text>
                  <Button
                    type="primary"
                    icon={item.status === 'completed' ? <CheckCircleOutlined /> : <PlayCircleOutlined />}
                    disabled={!item.available && item.status !== 'completed'}
                    onClick={() => navigate(`/learn/${item.path_id}/${encodeURIComponent(item.kp_id)}`)}
                  >
                    {item.status === 'completed' ? '再次学习' : item.available ? '开始学习' : '等待前置课程'}
                  </Button>
                </Space>
              </Card>
            </List.Item>
          )}
        />
      )}
    </div>
  )
}

function CourseDetail() {
  const { pathId, kpId } = useParams()
  const navigate = useNavigate()
  const [course, setCourse] = useState<Course | null>(null)
  const [learningPath, setLearningPath] = useState<LearningPath | null>(null)
  const [loading, setLoading] = useState(true)
  const [explanationDone, setExplanationDone] = useState(false)
  const [answers, setAnswers] = useState<Record<number, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [results, setResults] = useState<Record<number, any>>({})
  const [activeTab, setActiveTab] = useState<'explanation' | 'practice'>('explanation')
  const [evaluation, setEvaluation] = useState<MasteryEvaluation | null>(null)
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0)
  const [masterySync, setMasterySync] = useState<MasterySyncInfo | null>(null)
  const [syncingMastery, setSyncingMastery] = useState(false)

  useEffect(() => {
    if (!pathId || !kpId) return
    setLoading(true)
    setAnswers({})
    setResults({})
    setActiveTab('explanation')
    setEvaluation(null)
    setCurrentQuestionIndex(0)
    setMasterySync(null)
    Promise.all([
      coursesApi.get(Number(pathId), kpId),
      learningPathsApi.get(Number(pathId)),
    ])
      .then(([courseData, pathResult]) => {
        setCourse(courseData)
        setLearningPath(pathResult.data)
        setExplanationDone(courseData.progress.tasks.concept === 'completed')
        setEvaluation(courseData.progress.evaluation || null)
        setMasterySync(courseData.progress.mastery_sync || null)
        const answeredIds = new Set(courseData.progress.answered_question_ids || [])
        const firstUnanswered = courseData.questions.findIndex(
          (question) => !answeredIds.has(question.id),
        )
        setCurrentQuestionIndex(firstUnanswered >= 0 ? firstUnanswered : 0)
      })
      .catch((error) => message.error(errorText(error)))
      .finally(() => setLoading(false))
  }, [pathId, kpId])

  if (loading) return <Skeleton active />
  if (!course) return <Empty description="课程不存在" />
  const currentQuestion = course.questions[currentQuestionIndex]
  const currentAnswer = currentQuestion ? answers[currentQuestion.id]?.trim() : ''
  const currentResult = currentQuestion ? results[currentQuestion.id] : null

  const submit = async () => {
    if (!currentQuestion || !currentAnswer) return
    setSubmitting(true)
    try {
      const result = await coursesApi.complete(course.path_id, course.kp_id, {
        explanation_completed: explanationDone,
        answers: [{
          question_id: currentQuestion.id,
          ...(currentQuestion.question_type === 'choice'
            ? { selected_option: currentAnswer }
            : { answer_text: currentAnswer }),
        }],
      })
      setResults(Object.fromEntries(result.question_results.map((item: any) => [item.question_id, item])))
      setEvaluation(result.evaluation)
      message.success(
        result.evaluation.achieved
          ? '已达到本知识点掌握度目标'
          : '评估完成，可根据建议继续学习',
      )
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setSubmitting(false)
    }
  }

  const goToNextQuestion = () => {
    if (currentQuestionIndex < course.questions.length - 1) {
      setCurrentQuestionIndex((index) => index + 1)
    }
  }

  const syncMasteryToMap = async () => {
    if (!evaluation) {
      message.info('请先完成练习并生成掌握度评估')
      return
    }
    setSyncingMastery(true)
    try {
      const result = await coursesApi.syncMastery(course.path_id, course.kp_id)
      setMasterySync(result)
      message.success(`已将 ${result.mastery_score} 分掌握度同步到学习地图`)
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setSyncingMastery(false)
    }
  }

  const masteryIsCurrent = Boolean(
    evaluation
    && masterySync
    && Math.abs(masterySync.mastery_score - evaluation.mastery_score) < 0.05,
  )

  return (
    <div className="course-shell">
      {learningPath && <PathCatalog path={learningPath} currentKpId={course.kp_id} />}
      <main className="course-page">
        <div className="course-hero">
          <div className="course-hero-main">
            <div className="course-hero-tags">
              <span>阶段 {course.stage_index}</span>
              <span>{ROLE_LABEL[course.role] || course.role}</span>
              <span><ClockCircleOutlined /> 预计 {course.estimated_minutes} 分钟</span>
            </div>
            <Title level={2}>{course.kp_name}</Title>
            <Paragraph className="course-hero-summary">
              {course.explanation.summary || course.objectives[1]}
            </Paragraph>
          </div>
          <div className="course-mastery-panel">
            <div className="course-mastery">
              <div>
                <span>当前掌握度</span>
                <strong>{evaluation?.mastery_score ?? course.current_mastery ?? '待验证'}</strong>
              </div>
              <i />
              <div className="is-target">
                <span>目标掌握度</span>
                <strong>{Math.round(course.target_mastery)}</strong>
              </div>
            </div>
            <Button
              className="course-sync-button"
              icon={<SyncOutlined spin={syncingMastery} />}
              loading={syncingMastery}
              disabled={!evaluation}
              onClick={syncMasteryToMap}
            >
              {masteryIsCurrent ? '已同步到学习地图' : masterySync ? '重新同步到学习地图' : '同步到学习地图'}
            </Button>
          </div>
        </div>
        <div className="course-mode-picker" role="tablist" aria-label="学习方式">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'explanation'}
          className={activeTab === 'explanation' ? 'is-active' : ''}
          onClick={() => setActiveTab('explanation')}
        >
          <BookOutlined />
          <span><strong>知识讲解</strong><small>查看概念、方法与例题</small></span>
          {explanationDone && <CheckCircleOutlined className="mode-done" />}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'practice'}
          className={activeTab === 'practice' ? 'is-active' : ''}
          onClick={() => setActiveTab('practice')}
        >
          <PlayCircleOutlined />
          <span><strong>针对性刷题</strong><small>可以直接开始练习</small></span>
          {!!Object.keys(results).length && <CheckCircleOutlined className="mode-done" />}
        </button>
        </div>
        {course.warnings.map((warning) => <Alert key={warning} type="warning" showIcon message={warning} />)}

        {activeTab === 'explanation' && (
        <div className="course-explanation-layout">
        <div className="course-explanation-content">
        <Card className="lesson-card" title={<><BookOutlined /> {course.explanation.title}</>}>
        {course.explanation.summary && <Alert type="info" message={course.explanation.summary} />}
        <ExplanationBlocks
          blocks={course.explanation.content_blocks}
          fallbackContent={course.explanation.content}
        />
        {!!course.explanation.key_points.length && (
          <div className="lesson-points">
            <Title level={4}>学习要点</Title>
            <ul>{course.explanation.key_points.map((point) => <li key={point}>{point}</li>)}</ul>
          </div>
        )}
        {course.explanation.examples.map((example, index) => (
          <Card size="small" key={index} title={`例题 ${index + 1}`}>
            <Paragraph>{example.problem}</Paragraph>
            <Paragraph><Text strong>解答：</Text>{example.solution}</Paragraph>
            {example.explanation && <Paragraph type="secondary">{example.explanation}</Paragraph>}
          </Card>
        ))}
        <Checkbox checked={explanationDone} onChange={(event) => setExplanationDone(event.target.checked)}>
          我已完成讲解学习
        </Checkbox>
        </Card>

        <Card className="lesson-card" title={<><LinkOutlined /> 相关教学视频</>}>
        <List
          dataSource={course.external_resources}
          locale={{ emptyText: '当前知识点暂无已配置的教学视频' }}
          renderItem={(resource) => (
            <List.Item actions={[
              <a href={resource.url} target="_blank" rel="noreferrer">
                <PlayCircleOutlined /> 播放视频
              </a>,
            ]}>
              <List.Item.Meta
                title={<Space>{resource.title}<Tag color={resource.platform === '哔哩哔哩' ? 'blue' : 'red'}>{resource.platform}</Tag></Space>}
                description={resource.note}
              />
            </List.Item>
          )}
        />
        </Card>
        </div>
        <CourseTutorPanel course={course} />
        </div>
        )}

        {activeTab === 'practice' && (
        <Card className="lesson-card" title="针对性刷题">
        <section className={`mastery-evaluation ${evaluation?.achieved ? 'is-achieved' : ''}`}>
          <div className="mastery-evaluation-score">
            <Progress
              type="dashboard"
              size={126}
              percent={Math.round(evaluation?.mastery_score ?? course.current_mastery ?? 0)}
              strokeColor={evaluation?.achieved ? '#2e9d72' : '#16877c'}
              format={(percent) => <><strong>{percent}</strong><small>掌握度</small></>}
            />
          </div>
          <div className="mastery-evaluation-main">
            <div className="mastery-evaluation-title">
              <div>
                <Text type="secondary">本次学习评估</Text>
                <Title level={3}>
                  {evaluation
                    ? evaluation.achieved ? '已达到目标' : '继续巩固'
                    : '完成练习后生成评估'}
                </Title>
              </div>
              <Tag color={evaluation?.achieved ? 'success' : 'cyan'}>
                目标 {Math.round(course.target_mastery)} 分
              </Tag>
            </div>
            {evaluation ? (
              <>
                <div className="mastery-evaluation-stats">
                  <div><strong>{evaluation.correct_count}/{evaluation.answered_count}</strong><span>答对题目</span></div>
                  <div><strong>{Math.round((evaluation.accuracy || 0) * 100)}%</strong><span>原始正确率</span></div>
                  <div><strong>{Math.round(evaluation.weighted_accuracy * 100)}%</strong><span>难度加权正确率</span></div>
                  <div>
                    <strong>{evaluation.confidence_level === 'high' ? '高' : evaluation.confidence_level === 'medium' ? '中' : '低'}</strong>
                    <span>评估可信度</span>
                  </div>
                </div>
                <Alert
                  type={evaluation.achieved ? 'success' : evaluation.evidence_sufficient ? 'info' : 'warning'}
                  showIcon
                  message={evaluation.recommendation}
                />
                {evaluation.achieved && (
                  <div className="mastery-passed-actions">
                    <Text strong>这个知识点当前已过关</Text>
                    <Space>
                      <Button onClick={() => navigate(`/goals/${course.goal_id}/path`)}>
                        学习其他知识点
                      </Button>
                      {currentQuestionIndex < course.questions.length - 1 && (
                        <Button type="primary" onClick={goToNextQuestion}>
                          继续答题
                        </Button>
                      )}
                    </Space>
                  </div>
                )}
              </>
            ) : (
              <Paragraph type="secondary">
                至少完成 4 道题才会判断是否达标；建议完成 8 道以上，以获得更可靠的掌握度结果。
              </Paragraph>
            )}
          </div>
        </section>
        {!currentQuestion ? <Empty description="当前知识点暂无真题、模拟题或 AI 题" /> : (() => {
          const question = currentQuestion
          const result = currentResult
          const bankLabel = question.bank_type === 'real'
            ? '真题'
            : question.bank_type === 'ai' ? 'AI 题' : '模拟题'
          const optionEntries = Array.isArray(question.options)
            ? question.options.map((value, optionIndex) => [String.fromCharCode(65 + optionIndex), value])
            : Object.entries(question.options || {})
          return (
            <div className="practice-question" key={question.id}>
              <div className="practice-question-header">
                <Space wrap>
                  <Tag>第 {currentQuestionIndex + 1} 题</Tag>
                  <Tag color="blue">{bankLabel}</Tag>
                  <Tag>难度 {question.difficulty}</Tag>
                </Space>
                <Text type="secondary">{currentQuestionIndex + 1} / {course.questions.length}</Text>
              </div>
              <RichQuestionContent text={question.content} />
              {question.question_type === 'choice' ? (
                <Radio.Group
                  disabled={!!result}
                  value={answers[question.id]}
                  onChange={(event) => setAnswers({ ...answers, [question.id]: event.target.value })}
                >
                  <Space direction="vertical">
                    {optionEntries.map(([key, value]) => <Radio key={key} value={key}>{key}. {String(value)}</Radio>)}
                  </Space>
                </Radio.Group>
              ) : (
                <Input.TextArea
                  disabled={!!result}
                  value={answers[question.id]}
                  onChange={(event) => setAnswers({ ...answers, [question.id]: event.target.value })}
                  placeholder="请输入答案"
                />
              )}
              {result && <Alert type={result.is_correct ? 'success' : 'error'} showIcon message={result.is_correct ? '回答正确' : `回答错误，正确答案：${result.correct_answer || '-'}`} description={result.analysis} />}
            </div>
          )
        })()}
        {currentQuestion && !currentResult && (
          <Button
            type="primary"
            size="large"
            loading={submitting}
            disabled={!currentAnswer}
            onClick={submit}
          >
            提交本题并实时评估
          </Button>
        )}
        {currentResult && currentQuestionIndex < course.questions.length - 1 && (
          <Button type="primary" size="large" onClick={goToNextQuestion}>
            下一题
          </Button>
        )}
        {currentResult && currentQuestionIndex === course.questions.length - 1 && (
          <Alert type="info" showIcon message="已完成当前题组，可返回学习路径选择其他知识点" />
        )}
        </Card>
        )}
      </main>
    </div>
  )
}

export default function Learn() {
  const { pathId, kpId } = useParams()
  return pathId && kpId ? <CourseDetail /> : <CourseList />
}

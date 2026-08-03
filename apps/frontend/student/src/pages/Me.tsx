import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Collapse,
  Divider,
  Empty,
  Form,
  Input,
  Radio,
  Select,
  Segmented,
  Space,
  Spin,
  Statistic,
  Tag,
  Tabs,
  Typography,
  message,
} from 'antd'
import {
  BookOutlined,
  BulbOutlined,
  CloseCircleOutlined,
  FileDoneOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { authApi } from '../api/auth'
import {
  testsApi,
  TYPE_LABELS,
  type AiExercise,
  type AiExerciseResult,
  type WrongQuestionItem,
  type WrongQuestionList,
} from '../api/tests'
import { useAuth } from '../auth/AuthContext'
import {
  ExamQuestionBody,
  RichQuestionContent,
} from '../components/RichQuestionContent'
import './me.css'

type WrongFilter = 'all' | 'assessment' | 'practice'

function formatDate(value?: string | null) {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(value))
}

function WrongQuestionDetail({ item }: { item: WrongQuestionItem }) {
  const navigate = useNavigate()
  const initialExercise = item.generated_exercises?.[0] || null
  const [savedExercises, setSavedExercises] = useState(item.generated_exercises || [])
  const [exercise, setExercise] = useState<AiExercise | null>(initialExercise)
  const [result, setResult] = useState<AiExerciseResult | null>(
    initialExercise?.is_correct != null
      ? initialExercise as AiExerciseResult
      : null,
  )
  const [answer, setAnswer] = useState('')
  const [generating, setGenerating] = useState<'similar' | 'deeper' | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const generate = async (mode: 'similar' | 'deeper') => {
    setGenerating(mode)
    setExercise(null)
    setResult(null)
    setAnswer('')
    try {
      const { data } = await testsApi.generateWrongQuestionExercise(
        item.source_type,
        item.question_id,
        mode,
      )
      setExercise(data)
      setSavedExercises((current) => [data, ...current])
      message.success(mode === 'similar' ? '同类题已生成' : '加深题已生成')
    } catch (error: any) {
      message.error(error?.response?.data?.detail || 'AI 生成题目失败，请稍后重试')
    } finally {
      setGenerating(null)
    }
  }

  const submitExercise = async () => {
    if (!exercise || !answer.trim()) return
    setSubmitting(true)
    try {
      const { data } = await testsApi.submitWrongQuestionExercise(exercise.id, answer)
      setResult(data)
      setSavedExercises((current) => current.map((saved) => (
        saved.id === data.id ? data : saved
      )))
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '提交答案失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="wrong-detail">
      <ExamQuestionBody
        content={item.content}
        options={item.options}
        paperId={item.source_exam_paper_id}
      />
      <div className="wrong-detail__answers">
        <div>
          <span>你的答案</span>
          <strong className="wrong-detail__mine">{item.user_answer || '未作答'}</strong>
        </div>
        <div>
          <span>正确答案</span>
          <strong><RichQuestionContent text={item.correct_answer || '暂无'} paperId={item.source_exam_paper_id} /></strong>
        </div>
      </div>
      {item.analysis ? (
        <Alert
          type="info"
          showIcon
          message="题目解析"
          description={<RichQuestionContent text={item.analysis} paperId={item.source_exam_paper_id} />}
        />
      ) : null}
      {item.paper_id ? (
        <Button type="link" className="wrong-detail__link" onClick={() => navigate(`/exam/result/${item.paper_id}`)}>
          查看本次测评完整报告
        </Button>
      ) : item.path_id && item.kp_id ? (
        <Button type="link" className="wrong-detail__link" onClick={() => navigate(`/learn/${item.path_id}/${item.kp_id}`)}>
          返回知识点复习
        </Button>
      ) : null}

      <Divider />
      <section className="ai-practice">
        <div className="ai-practice__head">
          <div>
            <Typography.Title level={5}>
              <BulbOutlined /> AI 举一反三
            </Typography.Title>
            <Typography.Text type="secondary">
              根据这道错题生成新题，巩固相同考点或进一步提升难度。
            </Typography.Text>
            {savedExercises.length > 0 ? (
              <div className="ai-practice__history">
                <Typography.Text type="secondary">已保存 {savedExercises.length} 道：</Typography.Text>
                <Select
                  size="small"
                  value={exercise?.id}
                  placeholder="选择历史生成题"
                  options={savedExercises.map((saved, index) => ({
                    value: saved.id,
                    label: `${saved.mode === 'deeper' ? '加深题' : '同类题'} ${savedExercises.length - index}`,
                  }))}
                  onChange={(id) => {
                    const saved = savedExercises.find((candidate) => candidate.id === id) || null
                    setExercise(saved)
                    setAnswer(saved?.user_answer || '')
                    setResult(saved?.is_correct != null ? saved as AiExerciseResult : null)
                  }}
                />
              </div>
            ) : null}
          </div>
          <Space wrap>
            <Button
              icon={<BulbOutlined />}
              loading={generating === 'similar'}
              disabled={generating !== null}
              onClick={() => generate('similar')}
            >
              生成同类题
            </Button>
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              loading={generating === 'deeper'}
              disabled={generating !== null}
              onClick={() => generate('deeper')}
            >
              生成加深题
            </Button>
          </Space>
        </div>

        {exercise ? (
          <div className="ai-exercise">
            <div className="ai-exercise__meta">
              <Tag color="cyan">AI 生成</Tag>
              <Tag color={exercise.mode === 'deeper' ? 'purple' : 'blue'}>
                {exercise.mode === 'deeper' ? '加深题' : '同类题'}
              </Tag>
              <Tag>难度 {exercise.difficulty}/5</Tag>
            </div>
            <ExamQuestionBody content={exercise.content} options={exercise.options} />
            {!result ? (
              <div className="ai-exercise__answer">
                {exercise.question_type === 'choice' && exercise.options && typeof exercise.options === 'object' ? (
                  <Radio.Group
                    value={answer}
                    onChange={(event) => setAnswer(event.target.value)}
                    className="ai-exercise__choices"
                  >
                    {Object.keys(exercise.options as Record<string, unknown>).map((key) => (
                      <Radio.Button key={key} value={key}>{key}</Radio.Button>
                    ))}
                  </Radio.Group>
                ) : (
                  <Input.TextArea
                    value={answer}
                    onChange={(event) => setAnswer(event.target.value)}
                    placeholder="请输入你的答案"
                    autoSize={{ minRows: 2, maxRows: 6 }}
                  />
                )}
                <Button
                  type="primary"
                  disabled={!answer.trim()}
                  loading={submitting}
                  onClick={submitExercise}
                >
                  提交答案
                </Button>
              </div>
            ) : (
              <Alert
                type={result.is_correct ? 'success' : 'error'}
                showIcon
                message={result.is_correct ? '回答正确' : `回答错误，正确答案：${result.correct_answer}`}
                description={result.analysis}
              />
            )}
          </div>
        ) : null}
      </section>
    </div>
  )
}

export default function Me() {
  const { user, setUser, logout } = useAuth()
  const navigate = useNavigate()
  const [form] = Form.useForm()
  const [wrongData, setWrongData] = useState<WrongQuestionList | null>(null)
  const [wrongLoading, setWrongLoading] = useState(true)
  const [wrongError, setWrongError] = useState('')
  const [filter, setFilter] = useState<WrongFilter>('all')

  useEffect(() => {
    testsApi.wrongQuestions()
      .then(({ data }) => setWrongData(data))
      .catch((error) => setWrongError(error?.response?.data?.detail || '错题集加载失败'))
      .finally(() => setWrongLoading(false))
  }, [])

  const wrongItems = useMemo(() => {
    const items = wrongData?.items || []
    return filter === 'all' ? items : items.filter((item) => item.source_type === filter)
  }, [filter, wrongData])

  const onSave = async (values: { nickname?: string; password?: string }) => {
    try {
      const payload: { nickname?: string; password?: string } = {}
      if (values.nickname?.trim()) payload.nickname = values.nickname.trim()
      if (values.password) payload.password = values.password
      if (!payload.nickname && !payload.password) {
        message.info('没有可保存的修改')
        return
      }
      const { data } = await authApi.updateMe(payload)
      setUser(data)
      localStorage.setItem('student_user', JSON.stringify(data))
      form.setFieldValue('password', undefined)
      message.success('已保存')
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '保存失败')
    }
  }

  return (
    <div className="me-page">
      <Card className="me-tabs-card">
        <Tabs
          defaultActiveKey="wrong-questions"
          size="large"
          items={[
            {
              key: 'wrong-questions',
              label: (
                <Space>
                  <CloseCircleOutlined className="wrong-title-icon" />
                  错题集
                  {wrongData ? <span className="me-tab-count">{wrongData.total}</span> : null}
                </Space>
              ),
              children: (
                <div className="me-tab-panel">
                  {wrongLoading ? (
                    <div className="wrong-loading"><Spin /></div>
                  ) : wrongError ? (
                    <Alert type="error" showIcon message={wrongError} />
                  ) : (
                    <>
                      <div className="wrong-toolbar">
                        <div className="wrong-stats">
                          <Statistic title="全部错题" value={wrongData?.total || 0} prefix={<BookOutlined />} />
                          <Statistic title="测评错题" value={wrongData?.assessment_count || 0} prefix={<FileDoneOutlined />} />
                          <Statistic title="练习错题" value={wrongData?.practice_count || 0} prefix={<BookOutlined />} />
                        </div>
                        <Segmented
                          value={filter}
                          onChange={(value) => setFilter(value as WrongFilter)}
                          options={[
                            { label: '全部', value: 'all' },
                            { label: '测评', value: 'assessment' },
                            { label: '练习', value: 'practice' },
                          ]}
                        />
                      </div>
                      {wrongItems.length === 0 ? (
                        <Empty description={filter === 'all' ? '暂时没有错题，继续保持！' : '该分类暂无错题'} />
                      ) : (
                        <Collapse
                          className="wrong-list"
                          items={wrongItems.map((item) => ({
                            key: item.id,
                            label: (
                              <div className="wrong-list__label">
                                <Space wrap>
                                  <Tag color={item.source_type === 'assessment' ? 'volcano' : 'gold'}>
                                    {item.source_type === 'assessment' ? '测评' : '练习'}
                                  </Tag>
                                  <Tag>{TYPE_LABELS[item.question_type] || item.question_type}</Tag>
                                  <span>
                                    {item.paper_title
                                      ? `${item.paper_title}${item.seq ? ` · 第 ${item.seq} 题` : ''}`
                                      : '知识点练习'}
                                  </span>
                                </Space>
                                <Typography.Text type="secondary">{formatDate(item.created_at)}</Typography.Text>
                              </div>
                            ),
                            children: <WrongQuestionDetail item={item} />,
                          }))}
                        />
                      )}
                    </>
                  )}
                </div>
              ),
            },
            {
              key: 'account',
              label: '我的账号',
              children: (
                <div className="me-tab-panel">
                  <Typography.Paragraph>账号：{user?.email || user?.phone || '-'}</Typography.Paragraph>
                  <Form
                    form={form}
                    layout="vertical"
                    initialValues={{ nickname: user?.nickname || '' }}
                    onFinish={onSave}
                    style={{ maxWidth: 420 }}
                  >
                    <Form.Item name="nickname" label="昵称"><Input /></Form.Item>
                    <Form.Item name="password" label="新密码" extra="留空则不修改"><Input.Password /></Form.Item>
                    <Space>
                      <Button type="primary" htmlType="submit">保存</Button>
                      <Button danger onClick={() => { logout(); navigate('/login') }}>退出登录</Button>
                    </Space>
                  </Form>
                </div>
              ),
            },
          ]}
        />
      </Card>
    </div>
  )
}

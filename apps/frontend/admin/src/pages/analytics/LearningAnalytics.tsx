import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Col, Row, Select, Skeleton, Statistic, message } from 'antd'
import {
  BarChartOutlined,
  ReloadOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons'
import {
  analyticsApi,
  type KnowledgeDirectoryOptions,
  type KnowledgeScopeParams,
  type LearningAnalyticsResult,
} from '../../api'
import AnalyticsCurve from './AnalyticsCurve'
import KnowledgeScopeSelector from './KnowledgeScopeSelector'
import './learningAnalytics.css'

type StudentOption = { id: number; name: string; email?: string | null }

export default function LearningAnalytics({ mode }: { mode: 'population' | 'student' }) {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<LearningAnalyticsResult | null>(null)
  const [students, setStudents] = useState<StudentOption[]>([])
  const [studentId, setStudentId] = useState<number>()
  const [knowledgeOptions, setKnowledgeOptions] = useState<KnowledgeDirectoryOptions | null>(null)
  const [knowledgeOptionsLoading, setKnowledgeOptionsLoading] = useState(true)
  const [knowledgeScope, setKnowledgeScope] = useState<KnowledgeScopeParams>({})

  const loadPopulation = useCallback(async (scope: KnowledgeScopeParams = {}) => {
    setLoading(true)
    try {
      const response = await analyticsApi.getPopulation(scope)
      setData(response.data)
    } catch {
      message.error('普遍学习规律数据加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  const loadStudent = useCallback(async (id: number, scope: KnowledgeScopeParams = {}) => {
    setLoading(true)
    try {
      const response = await analyticsApi.getStudent(id, scope)
      setData(response.data)
    } catch {
      message.error('个性化参数数据加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    setKnowledgeOptionsLoading(true)
    analyticsApi.getKnowledgeOptions()
      .then(response => setKnowledgeOptions(response.data))
      .catch(() => message.error('知识点目录加载失败'))
      .finally(() => setKnowledgeOptionsLoading(false))

    if (mode === 'population') {
      void loadPopulation({})
      return
    }
    setLoading(true)
    analyticsApi.listStudents()
      .then(response => {
        setStudents(response.data)
        const first = response.data[0]?.id
        setStudentId(first)
        if (first) return loadStudent(first, {})
        setData(null)
        setLoading(false)
      })
      .catch(() => {
        message.error('学生列表加载失败')
        setLoading(false)
      })
  }, [loadPopulation, loadStudent, mode])

  const reload = () => {
    if (mode === 'population') void loadPopulation(knowledgeScope)
    else if (studentId) void loadStudent(studentId, knowledgeScope)
  }

  const changeKnowledgeScope = (scope: KnowledgeScopeParams) => {
    setKnowledgeScope(scope)
    if (mode === 'population') void loadPopulation(scope)
    else if (studentId) void loadStudent(studentId, scope)
  }

  const summary = data?.summary
  const isPopulation = mode === 'population'

  return (
    <div className="learning-analytics-page">
      <div className="analytics-page-header">
        <div>
          <h1>
            {isPopulation ? <TeamOutlined /> : <UserOutlined />}
            {isPopulation ? '普遍学习规律分析' : '个性化参数分析'}
          </h1>
          <p>
            {isPopulation
              ? '基于全体学生真实学习与测评行为，观察路径规划所需的群体基线参数'
              : '查看单个学生的掌握度、学习效率、迁移与遗忘等个性化参数'}
          </p>
        </div>
        <div className="analytics-header-actions">
          {!isPopulation && (
            <Select
              value={studentId}
              placeholder="请选择学生"
              showSearch
              optionFilterProp="label"
              style={{ width: 240 }}
              options={students.map(student => ({
                value: student.id,
                label: student.email ? `${student.name}（${student.email}）` : student.name,
              }))}
              onChange={id => {
                setStudentId(id)
                void loadStudent(id, knowledgeScope)
              }}
            />
          )}
          <Button icon={<ReloadOutlined />} onClick={reload} loading={loading}>刷新统计</Button>
        </div>
      </div>

      <KnowledgeScopeSelector
        options={knowledgeOptions}
        loading={knowledgeOptionsLoading}
        value={knowledgeScope}
        selectedCount={data?.knowledge_scope?.knowledge_point_count}
        onChange={changeKnowledgeScope}
      />

      {loading && !data ? (
        <Skeleton active paragraph={{ rows: 12 }} />
      ) : (
        <>
          {data && (
            <div className="analytics-summary">
              <Row gutter={[16, 16]}>
                <Col xs={12} md={6}>
                  <Statistic
                    title={isPopulation ? '纳入学生' : '学习目标'}
                    value={isPopulation ? summary?.student_count ?? 0 : summary?.goal_count ?? 0}
                    suffix={isPopulation ? '人' : '个'}
                  />
                </Col>
                <Col xs={12} md={6}>
                  <Statistic title="已批改测评" value={summary?.graded_paper_count ?? 0} suffix="份" />
                </Col>
                <Col xs={12} md={6}>
                  <Statistic title="有效作答证据" value={summary?.answer_event_count ?? 0} suffix="条" />
                </Col>
                <Col xs={12} md={6}>
                  <Statistic
                    title="达到统计门槛"
                    value={summary?.ready_parameter_count ?? 0}
                    suffix={`/ ${data.parameters.length} 项`}
                  />
                </Col>
              </Row>
            </div>
          )}

          <Alert
            className="analytics-evidence-alert"
            type={isPopulation && (summary?.student_count ?? 0) < 10 ? 'warning' : 'info'}
            showIcon
            message={
              isPopulation && (summary?.student_count ?? 0) < 10
                ? `当前仅有 ${summary?.student_count ?? 0} 名学生，群体规律暂不具备统计代表性`
                : '所有曲线均来自真实行为数据，空白指标表示当前尚无足够证据'
            }
            description="每张曲线均标注有效样本量；“样本较少”的结果可用于观察，但不会自动替换路径规划的稳定基线参数。"
          />

          {data ? (
            <div className="analytics-curve-grid">
              {data.parameters.map(parameter => (
                <AnalyticsCurve key={parameter.key} parameter={parameter} />
              ))}
            </div>
          ) : (
            <div className="analytics-no-student">
              <BarChartOutlined />
              <h3>暂无学生数据</h3>
              <p>学生开始学习和测评后，这里将生成个性化参数曲线。</p>
            </div>
          )}
        </>
      )}
    </div>
  )
}

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Row,
  Select,
  Skeleton,
  Statistic,
  Tag,
  message,
} from 'antd'
import {
  ApartmentOutlined,
  CheckSquareOutlined,
  DatabaseOutlined,
  InfoCircleOutlined,
  ReloadOutlined,
  RightOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import {
  analyticsApi,
  type DiagnosticPriorityAnalysisResult,
  type KnowledgeDirectoryOptions,
  type KnowledgeScopeParams,
  type MarginalMetric,
} from '../../api'
import KnowledgeScopeSelector from './KnowledgeScopeSelector'
import NodeMetricBarChart, { type NodeMetricBarGroup } from './NodeMetricBarChart'
import './marginalValueAnalytics.css'

type StudentOption = { id: number; name: string; email?: string | null }

type IndicatorRole = 'input' | 'derived' | 'result'

type IndicatorDefinition = {
  key: string
  name: string
  description: string
  formula: string
  source: string
  role: IndicatorRole
  symbol?: string
  usedBy: string
}

type FlowStage = {
  key: string
  title: string
  subtitle: string
  icon: React.ReactNode
  indicators: IndicatorDefinition[]
}

const DEFINITIONS: Record<string, IndicatorDefinition> = {
  total_score: {
    key: 'total_score',
    name: '目标试卷总分',
    description: '当前学习目标对应考试的试卷总分。',
    formula: '直接输入',
    source: '学习目标与目标试卷',
    role: 'input',
    symbol: 'S',
    usedBy: '与考试权重 W 相乘，计算考试分值影响范围 R',
  },
  confidence: {
    key: 'confidence',
    name: '评估可信度',
    description: '系统当前对该知识点评估结果的可信程度。',
    formula: '直接输入',
    source: '认知地图',
    role: 'input',
    symbol: 'C',
    usedBy: '计算当前标准证据量 E 和诊断不确定度 U',
  },
  target_confidence: {
    key: 'target_confidence',
    name: '目标可信度',
    description: '知识点退出诊断候选所需达到的可信度门槛。',
    formula: '系统参数：70%',
    source: '诊断策略配置',
    role: 'input',
    symbol: 'C₀',
    usedBy: '计算目标标准证据量 E₀',
  },
  effective_evidence: {
    key: 'effective_evidence',
    name: '诊断标准证据量',
    description: '把不同来源的可信度统一折算到诊断题量模型中的标准证据尺度。',
    formula: 'E = -3 × ln(1 - C)',
    source: '当前评估可信度',
    role: 'derived',
    symbol: 'E',
    usedBy: '与目标标准证据量 E₀ 比较，计算建议补测题数 Q',
  },
  target_evidence: {
    key: 'target_evidence',
    name: '目标标准证据量',
    description: '目标可信度折算到诊断题量模型后的标准证据量。',
    formula: 'E₀ = -3 × ln(1 - C₀)',
    source: '目标可信度',
    role: 'derived',
    symbol: 'E₀',
    usedBy: '与当前标准证据量 E 比较，计算建议补测题数 Q',
  },
  exam_weight: {
    key: 'exam_weight',
    name: '考试权重',
    description: '该知识点在目标考试中预计占据的分值比例。',
    formula: '知识点预计分值 ÷ 试卷总分',
    source: '试卷模板，缺失时使用目标测评统计',
    role: 'input',
    symbol: 'W',
    usedBy: '与目标试卷总分 S 相乘，得到考试分值影响范围 R',
  },
  minutes_per_question: {
    key: 'minutes_per_question',
    name: '单题标准时间',
    description: '完成一道诊断题预计需要的标准时间。',
    formula: '系统参数：3分钟/题',
    source: '诊断策略配置',
    role: 'input',
    symbol: 't',
    usedBy: '与建议测评题数 Q 相乘，计算预计测评时间 T',
  },
  uncertainty: {
    key: 'uncertainty',
    name: '诊断不确定度',
    description: '当前判断中仍未被有效证据消除的不确定程度。',
    formula: 'U = 1 - C',
    source: '评估可信度',
    role: 'derived',
    symbol: 'U',
    usedBy: '与考试分值影响范围 R 相乘，得到诊断信息价值 V',
  },
  score_exposure: {
    key: 'score_exposure',
    name: '考试分值影响范围',
    description: '如果该知识点判断错误，可能影响的目标考试分值规模。',
    formula: 'R = S × W',
    source: '目标试卷总分、考试权重',
    role: 'derived',
    symbol: 'R',
    usedBy: '与诊断不确定度 U 相乘，得到诊断信息价值 V',
  },
  recommended_question_count: {
    key: 'recommended_question_count',
    name: '建议测评题数',
    description: '预计把该知识点可信度提升到70%至少需要补充的有效题数。',
    formula: 'Q = clamp(ceil(E₀ - E), 1, 5)',
    source: '当前标准证据量、目标标准证据量',
    role: 'derived',
    symbol: 'Q',
    usedBy: '与单题标准时间 t 相乘，得到预计测评时间 T',
  },
  diagnostic_estimated_minutes: {
    key: 'diagnostic_estimated_minutes',
    name: '预计测评时间',
    description: '完成建议测评题目预计需要占用的时间。',
    formula: 'T = Q × t',
    source: '建议测评题数、单题标准时间',
    role: 'derived',
    symbol: 'T',
    usedBy: '作为诊断任务优先级 P 的时间成本分母',
  },
  diagnostic_information_value: {
    key: 'diagnostic_information_value',
    name: '诊断信息价值',
    description: '通过补测可以消除的考试相关不确定性。它不是预计提分，只用于决定先测什么。',
    formula: 'V = R × U',
    source: '考试分值影响范围、评估可信度',
    role: 'derived',
    symbol: 'V',
    usedBy: '作为诊断任务优先级 P 的信息收益分子',
  },
  diagnostic_priority: {
    key: 'diagnostic_priority',
    name: '诊断任务优先级',
    description: '每投入一分钟测评可以消除多少考试相关不确定性，数值越高越优先测评。',
    formula: 'P = V ÷ T',
    source: '诊断信息价值、预计测评时间',
    role: 'result',
    symbol: 'P',
    usedBy: '按数值从高到低生成建议测评顺序',
  },
  diagnostic_rank: {
    key: 'diagnostic_rank',
    name: '建议测评顺序',
    description: '按诊断任务优先级从高到低得到的推荐测评顺序。',
    formula: '按 P 降序；P 相同时按 V 降序',
    source: '诊断任务优先级',
    role: 'result',
    usedBy: '直接输出为后续测评任务的推荐次序',
  },
}

const FLOW_STAGES: FlowStage[] = [
  {
    key: 'raw',
    title: '① 计算输入',
    subtitle: '下面5项全部进入后续公式',
    icon: <DatabaseOutlined />,
    indicators: [
      DEFINITIONS.confidence,
      DEFINITIONS.exam_weight,
      DEFINITIONS.total_score,
      DEFINITIONS.target_confidence,
      DEFINITIONS.minutes_per_question,
    ],
  },
  {
    key: 'processed',
    title: '② 证据与成本参数',
    subtitle: '生成证据、可信度、影响范围与成本',
    icon: <ApartmentOutlined />,
    indicators: [
      DEFINITIONS.effective_evidence,
      DEFINITIONS.target_evidence,
      DEFINITIONS.uncertainty,
      DEFINITIONS.score_exposure,
      DEFINITIONS.recommended_question_count,
      DEFINITIONS.diagnostic_estimated_minutes,
    ],
  },
  {
    key: 'value',
    title: '③ 诊断信息收益',
    subtitle: '衡量补测能够减少的不确定性',
    icon: <SafetyCertificateOutlined />,
    indicators: [DEFINITIONS.diagnostic_information_value],
  },
  {
    key: 'result',
    title: '④ 后续评测策略',
    subtitle: '单位时间信息收益决定测评顺序',
    icon: <CheckSquareOutlined />,
    indicators: [
      DEFINITIONS.diagnostic_priority,
      DEFINITIONS.diagnostic_rank,
    ],
  },
]

const ROLE_META: Record<IndicatorRole, { label: string; color: string }> = {
  input: { label: '计算输入', color: 'green' },
  derived: { label: '中间结果', color: 'blue' },
  result: { label: '排序结果', color: 'purple' },
}

function average(metric?: MarginalMetric) {
  const values = metric?.curve
    .map(point => point.value)
    .filter((value): value is number => typeof value === 'number') ?? []
  if (!values.length) return null
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

function formatMetric(metric?: MarginalMetric) {
  const value = average(metric)
  if (value == null) return '暂无值'
  const digits = Math.abs(value) >= 10 ? 1 : 3
  return `${value.toFixed(digits)}${metric?.unit ?? ''}`
}

const CONFIDENCE_EXAMPLES = [
  { count: 1, confidence: '18.1%' },
  { count: 2, confidence: '33.0%' },
  { count: 3, confidence: '45.1%' },
  { count: 4, confidence: '55.1%' },
  { count: 8, confidence: '79.8%' },
  { count: 9, confidence: '83.5%' },
]

function ConfidenceRulePanel({ currentMean }: { currentMean: string }) {
  return (
    <section className="diagnostic-confidence-rules">
      <div className="diagnostic-confidence-heading">
        <div>
          <h3>评估可信度怎样取值</h3>
          <p>表示系统有多少答题证据支撑掌握度判断，不表示掌握度高低。</p>
        </div>
        <Tag color="cyan">当前候选均值 {currentMean}</Tag>
      </div>

      <div className="diagnostic-confidence-formula">
        <strong>课程刷题同步公式</strong>
        <code>C = 1 - exp(-n ÷ 5)</code>
        <span>n 为该知识点的有效答题数；答对或答错都会增加证据数量。</span>
      </div>

      <table className="diagnostic-confidence-table">
        <thead>
          <tr>
            <th>有效答题数 n</th>
            <th>评估可信度 C</th>
          </tr>
        </thead>
        <tbody>
          {CONFIDENCE_EXAMPLES.map(item => (
            <tr key={item.count}>
              <td>{item.count}题</td>
              <td>{item.confidence}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="diagnostic-confidence-levels">
        <span><b>低</b>C &lt; 55%</span>
        <span><b>中</b>55% ≤ C &lt; 80%</span>
        <span><b>高</b>C ≥ 80%</span>
        <span><b>达标判断</b>至少完成4题</span>
      </div>

      <div className="diagnostic-confidence-source-note">
        <strong>正式测评来源：</strong>
        <span>C = 1 - exp(-E ÷ 3)，E 是经过时间、难度、正误和知识关系加权后的证据量。</span>
      </div>
      <p className="diagnostic-confidence-average-note">
        折线上的每个点是一个候选知识点的可信度；“当前候选均值”是这些知识点可信度的平均数，不是答题数量。
      </p>
    </section>
  )
}

export default function DiagnosticPriorityAnalytics() {
  const [students, setStudents] = useState<StudentOption[]>([])
  const [studentId, setStudentId] = useState<number>()
  const [knowledgeOptions, setKnowledgeOptions] = useState<KnowledgeDirectoryOptions | null>(null)
  const [knowledgeScope, setKnowledgeScope] = useState<KnowledgeScopeParams>({})
  const [data, setData] = useState<DiagnosticPriorityAnalysisResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedKey, setSelectedKey] = useState<string>()

  const loadData = useCallback(async (id: number, scope: KnowledgeScopeParams = {}) => {
    setLoading(true)
    try {
      const response = await analyticsApi.getDiagnosticPriority(id, scope)
      setData(response.data)
    } catch {
      message.error('诊断任务优先级数据加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    Promise.all([analyticsApi.listStudents(), analyticsApi.getKnowledgeOptions()])
      .then(([studentResponse, knowledgeResponse]) => {
        setStudents(studentResponse.data)
        setKnowledgeOptions(knowledgeResponse.data)
        const first = studentResponse.data[0]?.id
        setStudentId(first)
        if (first) return loadData(first, {})
        setLoading(false)
      })
      .catch(() => {
        message.error('分析基础数据加载失败')
        setLoading(false)
      })
  }, [loadData])

  const metricMap = useMemo(
    () => new Map((data?.metrics ?? []).map(metric => [metric.key, metric])),
    [data],
  )
  const selectedDefinition = selectedKey ? DEFINITIONS[selectedKey] : undefined
  const selectedMetric = selectedKey ? metricMap.get(selectedKey) : undefined
  const metricValue = (key: string) => average(metricMap.get(key))
  const singleMetricGroup = (
    key: string,
    title: string,
    description: string,
  ): NodeMetricBarGroup => ({
    title,
    description,
    primaryLabel: '当前候选均值',
    rows: [{
      label: DEFINITIONS[key]?.name ?? key,
      value: metricValue(key),
      unit: metricMap.get(key)?.unit ?? '',
    }],
  })
  const confidenceGroup: NodeMetricBarGroup = {
    title: '当前可信度与诊断目标',
    description: '当前可信度低于目标可信度的知识点进入诊断候选。',
    primaryLabel: '当前候选均值',
    rows: [
      { label: '当前可信度 C', value: metricValue('confidence'), unit: '%' },
      { label: '目标可信度 C₀', value: metricValue('target_confidence'), unit: '%' },
    ],
  }
  const evidenceGroup: NodeMetricBarGroup = {
    title: '标准证据量缺口',
    description: '当前标准证据量 E 与目标证据量 E₀ 的差值决定建议补测题量。',
    primaryLabel: '当前候选均值',
    rows: [
      { label: '当前证据量 E', value: metricValue('effective_evidence'), unit: '份' },
      { label: '目标证据量 E₀', value: metricValue('target_evidence'), unit: '份' },
    ],
  }
  const uncertaintyGroup: NodeMetricBarGroup = {
    title: '可信度与剩余不确定度',
    description: '诊断不确定度 U = 100% - 当前可信度 C。',
    primaryLabel: '当前候选均值',
    rows: [
      { label: '评估可信度 C', value: metricValue('confidence'), unit: '%' },
      { label: '诊断不确定度 U', value: metricValue('uncertainty'), unit: '%' },
    ],
  }
  const exposureGroup: NodeMetricBarGroup = {
    title: '考试总分与知识点分值影响范围',
    description: '目标试卷总分 S 乘以考试权重 W，得到分值影响范围 R。',
    primaryLabel: '当前候选均值',
    rows: [
      { label: '目标试卷总分 S', value: metricValue('total_score'), unit: '分' },
      { label: '分值影响范围 R', value: metricValue('score_exposure'), unit: '分' },
    ],
  }
  const questionCountGroup: NodeMetricBarGroup = {
    title: '证据缺口换算题量',
    description: '建议测评题数 Q 由目标证据量与当前证据量的差值计算。',
    primaryLabel: '当前候选均值',
    rows: [
      {
        label: '建议测评题数 Q',
        value: metricValue('recommended_question_count'),
        unit: '题',
      },
    ],
  }
  const minutesPerQuestionGroup: NodeMetricBarGroup = {
    title: '单题标准时间输入',
    description: '每道诊断题使用的标准时间参数 t。',
    primaryLabel: '当前候选均值',
    rows: [{
      label: '单题标准时间 t',
      value: metricValue('minutes_per_question'),
      unit: '分钟/题',
    }],
  }
  const timeGroup: NodeMetricBarGroup = {
    title: '诊断时间成本',
    description: '建议测评题数 Q 乘以单题标准时间 t，得到预计测评时间 T。',
    primaryLabel: '当前候选均值',
    rows: [{
      label: '预计测评时间 T',
      value: metricValue('diagnostic_estimated_minutes'),
      unit: '分钟',
    }],
  }
  const informationValueGroup: NodeMetricBarGroup = {
    title: '诊断信息价值组成',
    description: '考试分值影响范围 R 乘以诊断不确定度 U，得到信息价值 V。',
    primaryLabel: '当前候选均值',
    rows: [
      { label: '分值影响范围 R', value: metricValue('score_exposure'), unit: '分' },
      {
        label: '诊断信息价值 V',
        value: metricValue('diagnostic_information_value'),
        unit: '分',
      },
    ],
  }
  const priorityGroups: NodeMetricBarGroup[] = [
    informationValueGroup,
    {
      title: '时间成本分母',
      description: '预计测评时间 T 是诊断优先级公式的成本分母。',
      primaryLabel: '当前候选均值',
      rows: [{
        label: '预计测评时间 T',
        value: metricValue('diagnostic_estimated_minutes'),
        unit: '分钟',
      }],
    },
    {
      title: '最终诊断任务优先级',
      description: '信息价值 V 除以预计测评时间 T，得到单位时间诊断收益 P。',
      primaryLabel: '当前候选均值',
      rows: [{
        label: '诊断优先级 P',
        value: metricValue('diagnostic_priority'),
        unit: '分/分钟',
      }],
    },
  ]
  const nodeCharts: Record<string, NodeMetricBarGroup[]> = {
    total_score: [exposureGroup],
    confidence: [confidenceGroup, uncertaintyGroup, evidenceGroup],
    target_confidence: [confidenceGroup, evidenceGroup],
    effective_evidence: [evidenceGroup],
    target_evidence: [evidenceGroup],
    exam_weight: [
      singleMetricGroup(
        'exam_weight',
        '知识点考试权重',
        '考试权重 W 与目标试卷总分 S 共同决定分值影响范围 R。',
      ),
      exposureGroup,
    ],
    minutes_per_question: [minutesPerQuestionGroup, questionCountGroup, timeGroup],
    uncertainty: [uncertaintyGroup],
    score_exposure: [exposureGroup],
    recommended_question_count: [evidenceGroup, questionCountGroup],
    diagnostic_estimated_minutes: [
      questionCountGroup,
      minutesPerQuestionGroup,
      timeGroup,
    ],
    diagnostic_information_value: [uncertaintyGroup, informationValueGroup],
    diagnostic_priority: priorityGroups,
    diagnostic_rank: [
      ...priorityGroups,
      singleMetricGroup(
        'diagnostic_rank',
        '建议测评顺序',
        '按诊断优先级 P 从高到低生成最终测评顺序。',
      ),
    ],
  }
  const selectedCharts = selectedKey ? nodeCharts[selectedKey] ?? [] : []

  const changeScope = (scope: KnowledgeScopeParams) => {
    setKnowledgeScope(scope)
    if (studentId) void loadData(studentId, scope)
  }

  return (
    <div className="marginal-analysis-page diagnostic-analysis-page">
      <div className="analytics-page-header">
        <div>
          <h1><SafetyCertificateOutlined />测评任务优先级分析</h1>
          <p>分析哪些知识点最需要优先补测，为下一轮评测和路径重规划提供依据</p>
        </div>
        <div className="analytics-header-actions">
          <Select
            value={studentId}
            placeholder="请选择学生"
            style={{ width: 240 }}
            options={students.map(student => ({
              value: student.id,
              label: student.email ? `${student.name}（${student.email}）` : student.name,
            }))}
            onChange={id => {
              setStudentId(id)
              void loadData(id, knowledgeScope)
            }}
          />
          <Button
            icon={<ReloadOutlined />}
            loading={loading}
            onClick={() => studentId && void loadData(studentId, knowledgeScope)}
          >
            刷新计算
          </Button>
        </div>
      </div>

      <KnowledgeScopeSelector
        options={knowledgeOptions}
        loading={loading && !knowledgeOptions}
        value={knowledgeScope}
        selectedCount={data?.knowledge_scope?.knowledge_point_count}
        onChange={changeScope}
      />

      {loading && !data ? (
        <Skeleton active paragraph={{ rows: 16 }} />
      ) : data?.path ? (
        <>
          <div className="marginal-summary">
            <Row gutter={[16, 16]}>
              <Col xs={12} md={6}>
                <Statistic title="待诊断知识点" value={data.summary.candidate_count} suffix="个" />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="建议测评题量"
                  value={data.summary.total_recommended_questions ?? 0}
                  suffix="题"
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="预计测评时间"
                  value={data.summary.total_estimated_minutes ?? 0}
                  suffix="分钟"
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="最优先测评"
                  value={data.summary.highest_priority_kp || '暂无'}
                />
              </Col>
            </Row>
          </div>

          <Alert
            className="marginal-guide-alert"
            type="info"
            showIcon
            message="从左到右依次计算"
            description="第一列是全部输入；后面每张卡片的公式只使用左侧已经出现的数据。"
          />

          <section className="marginal-flow-board diagnostic-flow-board">
            <div className="marginal-formula">
              <span>诊断任务优先级</span>
              <strong>=</strong>
              <span>诊断信息价值</span>
              <strong>÷</strong>
              <span>预计测评时间</span>
            </div>
            <div className="marginal-flow">
              {FLOW_STAGES.map((stage, index) => (
                <div className="marginal-stage-wrap" key={stage.key}>
                  <article className={`marginal-stage marginal-stage-${stage.key}`}>
                    <header>
                      <span className="marginal-stage-icon">{stage.icon}</span>
                      <div>
                        <h3>{stage.title}</h3>
                        <p>{stage.subtitle}</p>
                      </div>
                    </header>
                    <div className="marginal-indicator-list">
                      {stage.indicators.map(indicator => (
                        <button
                          type="button"
                          className={`marginal-indicator diagnostic-indicator diagnostic-role-${indicator.role}`}
                          key={indicator.key}
                          onClick={() => setSelectedKey(indicator.key)}
                        >
                          <span>
                            <span className="diagnostic-indicator-title">
                              <strong>
                                {indicator.symbol ? `${indicator.symbol} · ` : ''}
                                {indicator.name}
                              </strong>
                              <Tag color={ROLE_META[indicator.role].color}>
                                {ROLE_META[indicator.role].label}
                              </Tag>
                            </span>
                            <small>
                              {indicator.role === 'input'
                                ? `来源：${indicator.source}`
                                : `公式：${indicator.formula}`}
                            </small>
                            <small className="diagnostic-indicator-used-by">
                              用于：{indicator.usedBy}
                            </small>
                          </span>
                          <em>{formatMetric(metricMap.get(indicator.key))}</em>
                        </button>
                      ))}
                    </div>
                  </article>
                  {index < FLOW_STAGES.length - 1 && (
                    <div className="marginal-flow-arrow"><RightOutlined /></div>
                  )}
                </div>
              ))}
            </div>
            <div className="marginal-constraints">
              <span><InfoCircleOutlined /> 诊断候选门槛</span>
              <span>评估可信度低于70%</span>
              <span>知识点具有有效考试权重</span>
            </div>
          </section>
        </>
      ) : (
        <Empty description="该学生尚未生成学习路径，暂无诊断任务优先级数据" />
      )}

      <Drawer
        width={760}
        open={Boolean(selectedDefinition)}
        title={selectedDefinition?.name}
        onClose={() => setSelectedKey(undefined)}
      >
        {selectedDefinition && (
          <div className="marginal-metric-detail">
            <Alert type="info" showIcon message={selectedDefinition.description} />
            <Descriptions bordered column={1} size="small">
              <Descriptions.Item label="链路角色">
                <Tag color={ROLE_META[selectedDefinition.role].color}>
                  {ROLE_META[selectedDefinition.role].label}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="数据来源">{selectedDefinition.source}</Descriptions.Item>
              <Descriptions.Item label="计算公式">
                <code>{selectedDefinition.formula}</code>
              </Descriptions.Item>
              <Descriptions.Item label="下游去向">{selectedDefinition.usedBy}</Descriptions.Item>
              <Descriptions.Item label="当前候选均值">
                <Tag color="cyan">{formatMetric(selectedMetric)}</Tag>
              </Descriptions.Item>
            </Descriptions>
            {selectedKey === 'confidence' && (
              <ConfidenceRulePanel currentMean={formatMetric(selectedMetric)} />
            )}
            <div className="node-metric-chart-list">
              {selectedCharts.map(group => (
                <NodeMetricBarChart group={group} key={group.title} />
              ))}
            </div>
          </div>
        )}
      </Drawer>
    </div>
  )
}

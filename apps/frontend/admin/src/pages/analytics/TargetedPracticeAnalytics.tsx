import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Progress,
  Row,
  Select,
  Skeleton,
  Statistic,
  Tag,
  message,
} from 'antd'
import {
  AimOutlined,
  ArrowRightOutlined,
  BarChartOutlined,
  BookOutlined,
  BranchesOutlined,
  CheckCircleOutlined,
  DatabaseOutlined,
  FilterOutlined,
  ReloadOutlined,
  RobotOutlined,
  UserOutlined,
} from '@ant-design/icons'
import {
  analyticsApi,
  type KnowledgeDirectoryOptions,
  type KnowledgeScopeParams,
  type TargetedPracticeAnalysisResult,
} from '../../api'
import KnowledgeScopeSelector from './KnowledgeScopeSelector'
import './marginalValueAnalytics.css'
import './targetedPracticeAnalytics.css'

type StudentOption = { id: number; name: string; email?: string | null }
type IndicatorRole = 'input' | 'derived' | 'decision' | 'result'

type IndicatorDefinition = {
  key: string
  name: string
  description: string
  formula: string
  source: string
  role: IndicatorRole
  usedBy: string
}

const DEFINITIONS: Record<string, IndicatorDefinition> = {
  template_question_count: {
    key: 'template_question_count',
    name: '学习目标对应的平均模板',
    description: '读取学习目标对应平均模板中当前知识点的真题题型统计。真题只参与比例统计，不进入练习候选池。',
    formula: '按学科、地区、考试类型解析平均模板',
    source: '试卷管理 → 平均模板 → 知识点题型统计',
    role: 'input',
    usedBy: '计算当前知识点的选择题、填空题和简答题比例',
  },
  choice_ratio: {
    key: 'choice_ratio',
    name: '当前知识点题型统计',
    description: '统计当前知识点在平均模板中的选择题、填空题和简答题数量，并换算为比例。',
    formula: '某题型比例 = 该题型题数 ÷ 当前知识点模板总题数',
    source: '平均模板知识点题型统计',
    role: 'derived',
    usedBy: '按本轮计划题量换算各题型配额',
  },
  planned_choice_count: {
    key: 'planned_choice_count',
    name: '本轮题型配额',
    description: '使用最大余数法把题型比例转换成整数题量，保证各题型配额之和等于本轮计划题量。',
    formula: '题型配额 = 最大余数法（题型比例 × 本轮题量）',
    source: '题型比例、本轮计划题量',
    role: 'decision',
    usedBy: '约束候选题筛选时每种题型的大致数量',
  },
  history_answer_count: {
    key: 'history_answer_count',
    name: '用户当前知识点历史作答',
    description: '汇总正式测评、课程练习、训练和检查点中属于当前知识点的有效作答。',
    formula: '按用户与知识点合并有效作答事件',
    source: '测评答案、练习任务答题历史',
    role: 'input',
    usedBy: '计算各难度实际正确率、能力估计和已做题集合',
  },
  observed_accuracy: {
    key: 'observed_accuracy',
    name: '各难度实际正确率',
    description: '按难度1～5统计该知识点历史作答的实际正确率；小样本使用平滑估计避免极端结果。',
    formula: '平滑正确率 =（答对数 + 2）÷（作答数 + 4）',
    source: '当前知识点历史作答',
    role: 'derived',
    usedBy: '与能力估计共同预测各难度答对概率',
  },
  ability_estimate: {
    key: 'ability_estimate',
    name: '用户能力值估计',
    description: '由当前掌握度初始化，并根据每次作答的难度和正误进行Elo式更新。',
    formula: 'θ ← θ + 0.22 ×（实际结果 - 预测概率）',
    source: '当前掌握度、历史题目难度与正误',
    role: 'derived',
    usedBy: '生成难度1～5的模型预测答对概率',
  },
  predicted_target_success: {
    key: 'predicted_target_success',
    name: '预测各难度答对概率',
    description: '融合历史正确率与能力模型预测，样本越多越相信历史数据，样本越少越相信能力模型。',
    formula: 'P = w × 平滑正确率 +（1-w）× Elo预测',
    source: '各难度实际正确率、用户能力估计',
    role: 'derived',
    usedBy: '选择最接近目标答对概率的难度',
  },
  target_difficulty: {
    key: 'target_difficulty',
    name: '选择最近发展区难度',
    description: '选择预计正确率最接近62%的难度；连续答错时提高到70%，连续答对时降低到55%以适度加难。',
    formula: 'arg min |预测答对概率 - 目标答对概率|',
    source: '预测答对概率、近期连续表现',
    role: 'decision',
    usedBy: '生成20%稍易、60%目标、20%稍难的难度配额',
  },
  mock_candidate_count: {
    key: 'mock_candidate_count',
    name: '按题型筛选候选题',
    description: '候选池严格限定为模拟题和AI题；目标难度上下1级以内优先模拟题，真题始终排除。',
    formula: '知识点 + 题型配额 + 难度配额 + bank_type ∈ {mock, ai}',
    source: '模拟题库、AI题库',
    role: 'decision',
    usedBy: '生成满足题型、难度和来源优先级的候选序列',
  },
  unique_selected_count: {
    key: 'unique_selected_count',
    name: '去重并优先未做题',
    description: '本轮题目ID严格去重；同等适配时优先选择用户历史未做过的题目。',
    formula: '本轮ID去重 + 未做题优先排序',
    source: '候选序列、用户已做题集合',
    role: 'decision',
    usedBy: '形成最终本轮练习题目',
  },
  selected_question_count: {
    key: 'selected_question_count',
    name: '生成本轮练习',
    description: '输出最终练习题；库存不足时按剩余候选自动补位，并向后台展示缺题预警。',
    formula: '模拟题优先 + AI题回退 + 题型不足自动补位',
    source: '去重后的候选题',
    role: 'result',
    usedBy: '学生端知识点针对性刷题',
  },
}

const ROLE_META: Record<IndicatorRole, { label: string; color: string }> = {
  input: { label: '数据输入', color: 'green' },
  derived: { label: '计算指标', color: 'blue' },
  decision: { label: '算法决策', color: 'gold' },
  result: { label: '选题结果', color: 'purple' },
}

function formatNumber(value: number | null | undefined, unit = '') {
  if (value == null) return '暂无'
  const digits = Number.isInteger(value) ? 0 : Math.abs(value) >= 10 ? 1 : 2
  return `${value.toFixed(digits)}${unit}`
}

type NodeChartRow = {
  label: string
  value: number | null
  unit: string
  comparisonValue?: number | null
  note?: string
}

type NodeChartGroup = {
  title: string
  description: string
  primaryLabel: string
  comparisonLabel?: string
  rows: NodeChartRow[]
}

function NodeMetricChart({ group }: { group: NodeChartGroup }) {
  const values = group.rows.flatMap(row => [
    typeof row.value === 'number' ? row.value : 0,
    typeof row.comparisonValue === 'number' ? row.comparisonValue : 0,
  ])
  const usesPercent = group.rows.every(row => row.unit === '%')
  const maximum = usesPercent ? 100 : Math.max(...values, 1)
  const widthOf = (value: number | null | undefined) =>
    `${Math.max(0, Math.min(100, ((value ?? 0) / maximum) * 100))}%`

  return (
    <section className="targeted-node-chart">
      <header>
        <div>
          <h3>{group.title}</h3>
          <p>{group.description}</p>
        </div>
        <div className="targeted-node-chart-legend">
          <span><i className="targeted-legend-primary" />{group.primaryLabel}</span>
          {group.comparisonLabel && (
            <span><i className="targeted-legend-secondary" />{group.comparisonLabel}</span>
          )}
        </div>
      </header>
      <div className="targeted-node-chart-body">
        {group.rows.map(row => (
          <div className="targeted-node-chart-row" key={`${group.title}-${row.label}`}>
            <strong>{row.label}</strong>
            <div className="targeted-node-bars">
              <div className="targeted-node-bar-line">
                <span style={{ width: widthOf(row.value) }} />
                <em>{formatNumber(row.value, row.unit)}</em>
              </div>
              {group.comparisonLabel && (
                <div className="targeted-node-bar-line targeted-node-bar-secondary">
                  <span style={{ width: widthOf(row.comparisonValue) }} />
                  <em>{formatNumber(row.comparisonValue, row.unit)}</em>
                </div>
              )}
            </div>
            <small>{row.note || ''}</small>
          </div>
        ))}
      </div>
    </section>
  )
}

function FlowNode({
  definition,
  value,
  extra,
  onClick,
}: {
  definition: IndicatorDefinition
  value: string
  extra?: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      className={`targeted-flow-node targeted-role-${definition.role}`}
      onClick={onClick}
    >
      <span className="targeted-flow-node-heading">
        <strong>{definition.name}</strong>
        <Tag color={ROLE_META[definition.role].color}>{ROLE_META[definition.role].label}</Tag>
      </span>
      <em>{value}</em>
      {extra && <small>{extra}</small>}
    </button>
  )
}

function FlowArrow() {
  return <span className="targeted-flow-arrow"><ArrowRightOutlined /></span>
}

export default function TargetedPracticeAnalytics() {
  const [students, setStudents] = useState<StudentOption[]>([])
  const [studentId, setStudentId] = useState<number>()
  const [questionCount, setQuestionCount] = useState(20)
  const [knowledgeOptions, setKnowledgeOptions] = useState<KnowledgeDirectoryOptions | null>(null)
  const [knowledgeScope, setKnowledgeScope] = useState<KnowledgeScopeParams>({})
  const [data, setData] = useState<TargetedPracticeAnalysisResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedKey, setSelectedKey] = useState<string>()

  const loadData = useCallback(
    async (id: number, count: number, scope: KnowledgeScopeParams = {}) => {
      setLoading(true)
      try {
        const response = await analyticsApi.getTargetedPractice(id, count, scope)
        setData(response.data)
      } catch {
        message.error('针对性刷题算法指标加载失败')
      } finally {
        setLoading(false)
      }
    },
    [],
  )

  useEffect(() => {
    setLoading(true)
    Promise.all([analyticsApi.listStudents(), analyticsApi.getKnowledgeOptions()])
      .then(([studentResponse, knowledgeResponse]) => {
        setStudents(studentResponse.data)
        setKnowledgeOptions(knowledgeResponse.data)
        const first = studentResponse.data[0]?.id
        setStudentId(first)
        if (first) return loadData(first, 20, {})
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
  const scopeCount = Math.max(data?.summary.knowledge_point_count ?? 0, 1)
  const typeMap = new Map((data?.type_distribution ?? []).map(item => [item.key, item]))
  const bankMap = new Map((data?.bank_distribution ?? []).map(item => [item.key, item]))
  const averagePerKnowledgePoint = (value?: number | null) =>
    value == null ? null : value / scopeCount
  const ratioText = [
    `选 ${formatNumber(typeMap.get('choice')?.template_weight, '%')}`,
    `填 ${formatNumber(typeMap.get('fill')?.template_weight, '%')}`,
    `简 ${formatNumber(typeMap.get('short_answer')?.template_weight, '%')}`,
  ].join(' · ')
  const quotaText = [
    `选 ${formatNumber(averagePerKnowledgePoint(typeMap.get('choice')?.planned_count), '题')}`,
    `填 ${formatNumber(averagePerKnowledgePoint(typeMap.get('fill')?.planned_count), '题')}`,
    `简 ${formatNumber(averagePerKnowledgePoint(typeMap.get('short_answer')?.planned_count), '题')}`,
  ].join(' · ')
  const candidateText = [
    `模拟 ${formatNumber(averagePerKnowledgePoint(bankMap.get('mock')?.candidate_count), '题')}`,
    `AI ${formatNumber(averagePerKnowledgePoint(bankMap.get('ai')?.candidate_count), '题')}`,
  ].join(' · ')
  const nodeValues: Record<string, string> = {
    template_question_count: formatNumber(data?.summary.average_template_question_count, '题'),
    choice_ratio: ratioText,
    planned_choice_count: quotaText,
    history_answer_count: formatNumber(
      averagePerKnowledgePoint(data?.summary.history_answer_count),
      '题',
    ),
    observed_accuracy: formatNumber(data?.summary.average_observed_accuracy, '%'),
    ability_estimate: formatNumber(data?.summary.average_ability_estimate, '级'),
    predicted_target_success: formatNumber(
      data?.summary.average_predicted_target_success,
      '%',
    ),
    target_difficulty: formatNumber(data?.summary.average_target_difficulty, '级'),
    mock_candidate_count: candidateText,
    unique_selected_count: formatNumber(
      averagePerKnowledgePoint(data?.summary.unique_selected_count),
      '题',
    ),
    selected_question_count: formatNumber(
      averagePerKnowledgePoint(data?.summary.selected_question_count),
      '题',
    ),
  }
  const typeRows = (data?.type_distribution ?? []).map(item => ({
    label: item.label,
    value: item.template_weight,
    unit: '%',
  }))
  const nodeCharts: Record<string, NodeChartGroup[]> = {
    template_question_count: [
      {
        title: '平均模板中的三类题型题数',
        description: '每个知识点在目标平均模板中的平均题数，三项之和对应链路节点的平均模板题量。',
        primaryLabel: '平均题数',
        rows: (data?.type_distribution ?? []).map(item => ({
          label: item.label,
          value: item.template_question_count,
          unit: '题',
        })),
      },
      {
        title: '平均模板题型占比',
        description: '由同一组平均模板题数换算，直接进入下一节点的题型比例。',
        primaryLabel: '模板占比',
        rows: typeRows,
      },
    ],
    choice_ratio: [
      {
        title: '选择题 / 填空题 / 简答题比例',
        description: '与链路节点中“选、填、简”三个指标逐项一致。',
        primaryLabel: '题型比例',
        rows: typeRows,
      },
    ],
    planned_choice_count: [
      {
        title: '本轮题型配额与实际入选',
        description: '计划配额由模板比例计算；实际入选受模拟题和AI题库存限制。',
        primaryLabel: '计划配额',
        comparisonLabel: '实际入选',
        rows: (data?.type_distribution ?? []).map(item => ({
          label: item.label,
          value: item.planned_count,
          comparisonValue: item.selected_count,
          unit: '题',
        })),
      },
    ],
    history_answer_count: [
      {
        title: '历史作答按难度分布',
        description: '各难度样本数之和等于当前范围内的历史有效作答题量。',
        primaryLabel: '有效作答数',
        rows: (data?.difficulty_distribution ?? []).map(item => ({
          label: `难度 ${item.difficulty}`,
          value: item.observed_sample_size,
          unit: '题',
          note: `实际正确率 ${
            item.observed_accuracy == null ? '暂无' : `${item.observed_accuracy.toFixed(1)}%`
          }`,
        })),
      },
    ],
    observed_accuracy: [
      {
        title: '各难度实际正确率与预测答对率',
        description: '主柱为历史实际正确率，辅柱为融合能力模型后的预测答对率。',
        primaryLabel: '实际正确率',
        comparisonLabel: '预测答对率',
        rows: (data?.difficulty_distribution ?? []).map(item => ({
          label: `难度 ${item.difficulty}`,
          value: item.observed_accuracy ?? null,
          comparisonValue: item.predicted_success ?? null,
          unit: '%',
          note: `历史样本 ${item.observed_sample_size} 题`,
        })),
      },
    ],
    ability_estimate: [
      {
        title: '各知识点用户能力估计',
        description: '逐知识点展示能力值，均值与链路节点显示值一致。',
        primaryLabel: '能力估计',
        rows: (metricMap.get('ability_estimate')?.curve ?? []).map(point => ({
          label: point.label,
          value: point.value,
          unit: '级',
        })),
      },
    ],
    predicted_target_success: [
      {
        title: '难度1～5预测答对概率',
        description: '展示能力模型与历史正确率融合后的预测结果。',
        primaryLabel: '预测答对率',
        comparisonLabel: '历史实际正确率',
        rows: (data?.difficulty_distribution ?? []).map(item => ({
          label: `难度 ${item.difficulty}`,
          value: item.predicted_success ?? null,
          comparisonValue: item.observed_accuracy ?? null,
          unit: '%',
          note: `历史样本 ${item.observed_sample_size} 题`,
        })),
      },
    ],
    target_difficulty: [
      {
        title: '最近发展区难度配额与实际入选',
        description: '目标难度按20%稍易、60%目标、20%稍难生成计划，并与实际库存选题对比。',
        primaryLabel: '计划难度配额',
        comparisonLabel: '实际入选',
        rows: (data?.difficulty_distribution ?? []).map(item => ({
          label: `难度 ${item.difficulty}`,
          value: item.planned_count,
          comparisonValue: item.selected_count,
          unit: '题',
          note: `预测答对率 ${
            item.predicted_success == null ? '暂无' : `${item.predicted_success.toFixed(1)}%`
          }`,
        })),
      },
    ],
    mock_candidate_count: [
      {
        title: '题库候选数与实际入选数',
        description: '模拟题和AI题进入候选池；真题只显示排除数量，入选数始终为0。',
        primaryLabel: '候选库存',
        comparisonLabel: '实际入选',
        rows: (data?.bank_distribution ?? []).map(item => ({
          label: item.label,
          value: item.candidate_count,
          comparisonValue: item.selected_count,
          unit: '题',
        })),
      },
    ],
    unique_selected_count: [
      {
        title: '本轮去重结果',
        description: '最终入选题目ID严格去重，并统计其中用户历史已经做过的题目。',
        primaryLabel: '题量',
        rows: [
          {
            label: '最终入选',
            value: data?.summary.selected_question_count ?? 0,
            unit: '题',
          },
          {
            label: '去重后题目',
            value: data?.summary.unique_selected_count ?? 0,
            unit: '题',
          },
          {
            label: '历史已做题',
            value: data?.summary.repeated_selected_count ?? 0,
            unit: '题',
          },
        ],
      },
    ],
    selected_question_count: [
      {
        title: '最终练习题来源',
        description: '最终题目只由模拟题和AI题构成，真题入选数必须为0。',
        primaryLabel: '实际入选',
        rows: (data?.bank_distribution ?? []).map(item => ({
          label: item.label,
          value: item.selected_count,
          unit: '题',
        })),
      },
      {
        title: '最终练习题型结构',
        description: '展示本轮最终生成练习的题型构成。',
        primaryLabel: '实际入选',
        rows: (data?.type_distribution ?? []).map(item => ({
          label: item.label,
          value: item.selected_count,
          unit: '题',
        })),
      },
    ],
  }
  const selectedCharts = selectedKey ? nodeCharts[selectedKey] ?? [] : []

  const changeScope = (scope: KnowledgeScopeParams) => {
    setKnowledgeScope(scope)
    if (studentId) void loadData(studentId, questionCount, scope)
  }

  const warnings = data?.summary.warnings ?? []
  const selectedTotal = data?.summary.selected_question_count ?? 0
  const plannedTotal = data?.summary.planned_question_count ?? 0

  return (
    <div className="marginal-analysis-page targeted-analysis-page">
      <div className="analytics-page-header">
        <div>
          <h1><BranchesOutlined />针对新刷题算法指标</h1>
          <p className="targeted-analysis-principle">
            根据平均模板决定题型比例，根据历史答题难易题的准确率选择最近发展区的题目。
          </p>
          <p className="targeted-analysis-subtitle">
            跟踪平均模板、历史能力、难度决策、题库筛选与最终练习生成的完整数据链路
          </p>
        </div>
        <div className="analytics-header-actions">
          <Select
            value={studentId}
            placeholder="请选择学生"
            style={{ width: 220 }}
            options={students.map(student => ({
              value: student.id,
              label: student.email ? `${student.name}（${student.email}）` : student.name,
            }))}
            onChange={id => {
              setStudentId(id)
              void loadData(id, questionCount, knowledgeScope)
            }}
          />
          <Select
            value={questionCount}
            style={{ width: 130 }}
            options={[10, 15, 20, 25, 30].map(value => ({
              value,
              label: `每知识点 ${value} 题`,
            }))}
            onChange={value => {
              setQuestionCount(value)
              if (studentId) void loadData(studentId, value, knowledgeScope)
            }}
          />
          <Button
            icon={<ReloadOutlined />}
            loading={loading}
            onClick={() => studentId && void loadData(studentId, questionCount, knowledgeScope)}
          >
            刷新指标
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
        <Skeleton active paragraph={{ rows: 18 }} />
      ) : data?.path ? (
        <>
          <div className="marginal-summary targeted-summary">
            <Row gutter={[16, 16]}>
              <Col xs={12} md={6}>
                <Statistic
                  title="本次跟踪知识点"
                  value={data.summary.knowledge_point_count}
                  suffix="个"
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="历史有效作答"
                  value={data.summary.history_answer_count ?? 0}
                  suffix="题"
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="可生成 / 计划题量"
                  value={selectedTotal}
                  suffix={`/ ${plannedTotal}题`}
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="入选题目来源"
                  value={data.summary.mock_selected_count ?? 0}
                  suffix={`道模拟 · ${data.summary.ai_selected_count ?? 0}道AI`}
                />
              </Col>
            </Row>
          </div>

          <Alert
            className="marginal-guide-alert"
            type={(data.summary.real_selected_count ?? 0) === 0 ? 'success' : 'error'}
            showIcon
            message="练习候选池已严格排除真题"
            description={`算法版本 ${data.path.algorithm_version}；平均模板只用于计算题型比例，实际入选真题 ${
              data.summary.real_selected_count ?? 0
            } 道。点击链路中的任一指标可查看各知识点曲线。`}
          />

          <section className="targeted-chain-board">
            <div className="targeted-chain-title">
              <div>
                <h2>一、整体数据链路</h2>
                <p>上方决定“出什么题型”，下方决定“出多难”，两条链路汇合后完成选题与去重。</p>
              </div>
              <Tag color="cyan">实时计算 · {data.summary.knowledge_point_count}个知识点</Tag>
            </div>

            <div className="targeted-chain-scroll">
              <div className="targeted-chain-lane targeted-chain-type">
                <span className="targeted-lane-label"><BookOutlined />题型链路</span>
                <FlowNode
                  definition={DEFINITIONS.template_question_count}
                  value={nodeValues.template_question_count}
                  extra={`模板覆盖 ${data.summary.template_covered_count ?? 0} 个知识点`}
                  onClick={() => setSelectedKey('template_question_count')}
                />
                <FlowArrow />
                <FlowNode
                  definition={DEFINITIONS.choice_ratio}
                  value={ratioText}
                  extra="选择 / 填空 / 简答"
                  onClick={() => setSelectedKey('choice_ratio')}
                />
                <FlowArrow />
                <FlowNode
                  definition={DEFINITIONS.planned_choice_count}
                  value={quotaText}
                  extra={`每知识点计划 ${data.summary.question_count_per_kp ?? questionCount} 题`}
                  onClick={() => setSelectedKey('planned_choice_count')}
                />
              </div>

              <div className="targeted-chain-lane targeted-chain-difficulty">
                <span className="targeted-lane-label"><UserOutlined />难度链路</span>
                <FlowNode
                  definition={DEFINITIONS.history_answer_count}
                  value={nodeValues.history_answer_count}
                  extra="正式测评 + 练习记录"
                  onClick={() => setSelectedKey('history_answer_count')}
                />
                <FlowArrow />
                <div className="targeted-parallel-nodes">
                  <FlowNode
                    definition={DEFINITIONS.observed_accuracy}
                    value={nodeValues.observed_accuracy}
                    onClick={() => setSelectedKey('observed_accuracy')}
                  />
                  <FlowNode
                    definition={DEFINITIONS.ability_estimate}
                    value={nodeValues.ability_estimate}
                    onClick={() => setSelectedKey('ability_estimate')}
                  />
                </div>
                <FlowArrow />
                <FlowNode
                  definition={DEFINITIONS.predicted_target_success}
                  value={nodeValues.predicted_target_success}
                  extra="融合历史正确率与Elo预测"
                  onClick={() => setSelectedKey('predicted_target_success')}
                />
                <FlowArrow />
                <FlowNode
                  definition={DEFINITIONS.target_difficulty}
                  value={nodeValues.target_difficulty}
                  extra="目标答对概率约62%"
                  onClick={() => setSelectedKey('target_difficulty')}
                />
              </div>

              <div className="targeted-chain-merge">
                <span className="targeted-merge-line" />
                <FlowNode
                  definition={DEFINITIONS.mock_candidate_count}
                  value={candidateText}
                  extra="真题不进入候选池"
                  onClick={() => setSelectedKey('mock_candidate_count')}
                />
                <FlowArrow />
                <FlowNode
                  definition={DEFINITIONS.unique_selected_count}
                  value={nodeValues.unique_selected_count}
                  extra={`历史已做 ${formatNumber(
                    averagePerKnowledgePoint(data.summary.repeated_selected_count),
                    '题',
                  )}`}
                  onClick={() => setSelectedKey('unique_selected_count')}
                />
                <FlowArrow />
                <FlowNode
                  definition={DEFINITIONS.selected_question_count}
                  value={nodeValues.selected_question_count}
                  extra={`本次共生成 ${selectedTotal} 题`}
                  onClick={() => setSelectedKey('selected_question_count')}
                />
              </div>
            </div>
          </section>

          <section className="targeted-monitor-grid">
            <article className="targeted-monitor-card">
              <header>
                <span><BarChartOutlined />题型配额执行情况</span>
                <Tag color="blue">平均模板驱动</Tag>
              </header>
              <div className="targeted-type-list">
                {data.type_distribution.map(item => {
                  const completion = item.planned_count
                    ? Math.min(100, (item.selected_count / item.planned_count) * 100)
                    : 0
                  return (
                    <div className="targeted-type-row" key={item.key}>
                      <div>
                        <strong>{item.label}</strong>
                        <span>模板平均占比 {item.template_weight.toFixed(1)}%</span>
                      </div>
                      <Progress
                        percent={Number(completion.toFixed(1))}
                        size="small"
                        strokeColor="#11877a"
                      />
                      <em>{item.selected_count} / {item.planned_count}题</em>
                    </div>
                  )
                })}
              </div>
            </article>

            <article className="targeted-monitor-card">
              <header>
                <span><AimOutlined />难度准确率与选题分布</span>
                <Tag color="gold">最近发展区</Tag>
              </header>
              <div className="targeted-difficulty-grid">
                {data.difficulty_distribution.map(item => (
                  <div className="targeted-difficulty-item" key={item.difficulty}>
                    <strong>难度 {item.difficulty}</strong>
                    <span>
                      实际正确率
                      <b>{item.observed_accuracy == null ? '暂无' : `${item.observed_accuracy.toFixed(1)}%`}</b>
                    </span>
                    <span>
                      预测答对率
                      <b>{item.predicted_success == null ? '暂无' : `${item.predicted_success.toFixed(1)}%`}</b>
                    </span>
                    <small>入选 {item.selected_count} / 计划 {item.planned_count}题</small>
                  </div>
                ))}
              </div>
            </article>

            <article className="targeted-monitor-card targeted-bank-card">
              <header>
                <span><DatabaseOutlined />候选池来源跟踪</span>
                <Tag color="green">模拟题优先</Tag>
              </header>
              <div className="targeted-bank-list">
                {data.bank_distribution.map(item => (
                  <div className={`targeted-bank-row targeted-bank-${item.key}`} key={item.key}>
                    <span className="targeted-bank-icon">
                      {item.key === 'mock'
                        ? <CheckCircleOutlined />
                        : item.key === 'ai'
                          ? <RobotOutlined />
                          : <FilterOutlined />}
                    </span>
                    <div>
                      <strong>{item.label}</strong>
                      <small>候选库存 {item.candidate_count} 题</small>
                    </div>
                    <em>入选 {item.selected_count} 题</em>
                  </div>
                ))}
              </div>
            </article>
          </section>

          {warnings.length > 0 && (
            <Alert
              className="targeted-warning"
              type="warning"
              showIcon
              message={`发现 ${warnings.length} 项题库或模板数据提醒`}
              description={
                <ul>
                  {warnings.slice(0, 5).map(warning => <li key={warning}>{warning}</li>)}
                </ul>
              }
            />
          )}
        </>
      ) : (
        <Empty description="该学生尚未生成学习路径，暂无针对性刷题算法指标" />
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
              <Descriptions.Item label="计算规则">
                <code>{selectedDefinition.formula}</code>
              </Descriptions.Item>
              <Descriptions.Item label="下游去向">{selectedDefinition.usedBy}</Descriptions.Item>
              <Descriptions.Item label="当前节点显示值">
                <Tag color="cyan">
                  {selectedKey ? nodeValues[selectedKey] ?? '暂无' : '暂无'}
                </Tag>
              </Descriptions.Item>
            </Descriptions>
            <div className="targeted-node-chart-list">
              {selectedCharts.map(group => (
                <NodeMetricChart group={group} key={group.title} />
              ))}
            </div>
          </div>
        )}
      </Drawer>
    </div>
  )
}

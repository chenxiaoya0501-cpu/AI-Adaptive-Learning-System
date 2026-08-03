import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Empty,
  Select,
  Skeleton,
  Tag,
  message,
} from 'antd'
import {
  ApartmentOutlined,
  CalculatorOutlined,
  DatabaseOutlined,
  InfoCircleOutlined,
  ReloadOutlined,
  RightOutlined,
  RiseOutlined,
} from '@ant-design/icons'
import {
  analyticsApi,
  type KnowledgeDirectoryOptions,
  type KnowledgeScopeParams,
  type MarginalMetric,
  type MarginalValueAnalysisResult,
} from '../../api'
import KnowledgeScopeSelector from './KnowledgeScopeSelector'
import NodeMetricBarChart, { type NodeMetricBarGroup } from './NodeMetricBarChart'
import './marginalValueAnalytics.css'

type StudentOption = { id: number; name: string; email?: string | null }

type IndicatorDefinition = {
  key: string
  name: string
  description: string
  formula: string
  source: string
  symbol?: string
  role?: 'input' | 'derived' | 'result'
  usedBy?: string
}

type FlowStage = {
  key: string
  title: string
  subtitle: string
  icon: React.ReactNode
  indicators: IndicatorDefinition[]
}

const DEFINITIONS: Record<string, IndicatorDefinition> = {
  current_mastery: {
    key: 'current_mastery',
    name: '当前掌握度',
    description: '由正式测评或用户主动同步的课程刷题结果得到，表示目前掌握水平。',
    formula: '掌握度评估结果（0～100分）',
    source: '测评作答、课程刷题同步',
  },
  target_mastery: {
    key: 'target_mastery',
    name: '目标掌握度',
    description: '路径规划希望该知识点达到的掌握水平，重要考点目标通常更高。',
    formula: '根据考试权重和认知层级确定，一般为75～90分',
    source: '学习目标、考试权重',
  },
  confidence: {
    key: 'confidence',
    name: '评估可信度',
    description: '衡量当前掌握度证据是否充分，作答证据越多通常越可靠。',
    formula: '1 - exp(-有效证据量 ÷ 3)',
    source: '有效作答数量与权重',
  },
  exam_weight: {
    key: 'exam_weight',
    name: '考试权重',
    description: '该知识点在目标考试总分中预计占据的比例。',
    formula: '知识点对应预计分值 ÷ 试卷总分',
    source: '试卷模板、真题统计',
  },
  recent_streak: {
    key: 'recent_streak',
    name: '近期连续表现',
    description: '最近连续答对或答错情况，用来修正短期可学会概率。',
    formula: '连续答对记正数，连续答错记负数，最多采用最近2次',
    source: '最近测评作答',
  },
  cognitive_base: {
    key: 'cognitive_base',
    name: '认知层级基础概率',
    description: '不同认知层级知识点的默认学习成功概率。',
    formula: '按了解、理解、掌握、运用配置基础概率',
    source: '课程标准知识点元数据',
  },
  relation_strength: {
    key: 'relation_strength',
    name: '知识关系强度',
    description: '表示前置知识点对后续知识点的影响强弱。',
    formula: '知识图谱关系权重',
    source: '知识图谱前后置关系',
  },
  effective_mastery: {
    key: 'effective_mastery',
    name: '有效掌握度',
    description: '可信度不足时，将当前掌握度向中性值50分收缩，避免过度相信少量证据。',
    formula: '可信度 × 当前掌握度 + (1 - 可信度) × 50',
    source: '当前掌握度、可信度',
  },
  mastery_gap: {
    key: 'mastery_gap',
    name: '掌握度差距',
    description: '该知识点距离规划目标还有多少可提升空间。',
    formula: 'max(0, 目标掌握度 - 有效掌握度)',
    source: '有效掌握度、目标掌握度',
  },
  learnability: {
    key: 'learnability',
    name: '可学会概率',
    description: '预计安排本轮学习后，学生真正掌握该知识点的概率。',
    formula: '认知层级基础概率 + 连续答对×4% - 连续答错×5%',
    source: '认知层级、近期连续表现',
  },
  transfer_rate: {
    key: 'transfer_rate',
    name: '迁移率',
    description: '课程中学会的内容能够在正式考试中正确应用的比例。',
    formula: '群体迁移基线 × 个人迁移修正',
    source: '试卷权重来源、认知层级；未来由学习后测评校准',
  },
  estimated_minutes: {
    key: 'estimated_minutes',
    name: '预计学习时间',
    description: '完成该知识点本轮学习预计需要的时间，是边际价值的成本项。',
    formula: '认知层级基础时长 × 掌握差距系数 × 不确定性系数',
    source: '认知层级、掌握差距、可信度',
  },
  direct_gain: {
    key: 'direct_gain',
    name: '直接提分价值',
    description: '学习该知识点本身预计能带来的考试分数提升。',
    formula: '总分 × 考试权重 × 掌握差距 × 可学会概率 × 迁移率',
    source: '考试权重、掌握差距、可学会概率、迁移率',
  },
  unlock_gain: {
    key: 'unlock_gain',
    name: '解锁后续知识价值',
    description: '学好前置知识后，为后续高价值知识点释放的潜在收益。',
    formula: '后续知识点收益 × 前后置关系强度，沿依赖链衰减',
    source: '知识图谱、后续知识点直接收益',
  },
  strategic_value: {
    key: 'strategic_value',
    name: '战略价值',
    description: '用于首轮学习路径排期的综合收益，只包含直接提分与后继解锁收益。',
    formula: '首轮直接预计提分 + 0.70 × 后继解锁预计收益',
    source: '直接提分价值、知识图谱后继收益',
  },
  marginal_value: {
    key: 'marginal_value',
    name: '边际价值',
    description: '每投入一分钟能够获得的综合学习价值，是知识点排序的核心指标。',
    formula: '战略价值 ÷ 预计学习时间',
    source: '战略价值、预计学习时间',
  },
  priority: {
    key: 'priority',
    name: '路径优先级',
    description: '按照边际价值从高到低，并满足前置关系后得到的实际学习顺序。',
    formula: '边际价值排序 + 前置依赖约束 + 总容量约束',
    source: '边际价值、知识图谱、时间约束',
  },
  daily_capacity: {
    key: 'daily_capacity',
    name: '每日可投入时间',
    description: '不改变知识点自身价值，只限制每天最多能够安排多少任务。',
    formula: '用户设置的每日学习分钟数',
    source: '学习目标配置',
  },
  remaining_days: {
    key: 'remaining_days',
    name: '目标剩余天数',
    description: '不改变单个知识点边际价值，用于计算路径总时间容量。',
    formula: '考试日期 - 当前日期',
    source: '学习目标日期',
  },
}

const CHAIN_DEFINITIONS: Record<string, IndicatorDefinition> = {
  current_mastery: {
    key: 'current_mastery',
    symbol: 'M',
    name: '当前掌握度',
    description: '由正式测评或用户主动同步的课程刷题结果得到，表示目前掌握水平。',
    formula: 'M = 掌握度评估结果（0～100分；无证据时为空）',
    source: '测评作答、课程刷题同步',
    role: 'input',
    usedBy: '与评估可信度 C 一起计算有效掌握度 Mₑ',
  },
  confidence: {
    key: 'confidence',
    symbol: 'C',
    name: '评估可信度',
    description: '衡量当前掌握度证据是否充分；这里使用路径生成时保存的可信度快照。',
    formula: 'C = 路径生成时保存的掌握度可信度（页面按百分比展示）',
    source: '掌握度快照',
    role: 'derived',
    usedBy: '与当前掌握度 M 一起计算有效掌握度 Mₑ',
  },
  target_mastery: {
    key: 'target_mastery',
    symbol: 'Mₜ',
    name: '首轮目标掌握度',
    description: '规划器计算本轮直接提分时真正使用的目标，不是包含后续强化后的最终目标。',
    formula: 'Mₜ = 路径节点保存的 base_target_mastery',
    source: '路径规划快照',
    role: 'input',
    usedBy: '与有效掌握度 Mₑ 一起计算掌握度差距 G',
  },
  total_score: {
    key: 'total_score',
    symbol: 'S',
    name: '目标试卷总分',
    description: '将知识点的考试权重换算成预计分值时使用的目标试卷总分。',
    formula: 'S = 目标试卷模板总分；无模板时取学习目标可用总分',
    source: '试卷模板、学习目标',
    role: 'input',
    usedBy: '与 W、G、L、τ 一起计算直接提分价值 D',
  },
  exam_weight: {
    key: 'exam_weight',
    symbol: 'W',
    name: '考试权重',
    description: '该知识点在目标考试总分中预计占据的比例。',
    formula: 'W = 知识点预计分值 ÷ 目标试卷总分（页面按百分比展示）',
    source: '试卷模板、真题统计',
    role: 'input',
    usedBy: '与 S、G、L、τ 一起计算直接提分价值 D',
  },
  learnability: {
    key: 'learnability',
    symbol: 'L',
    name: '可学会概率',
    description: '可学会子模型对“本轮学习后能真正掌握”的估计，作为核心价值链的已计算输入。',
    formula: 'L = 路径规划器保存的 learnability（页面按百分比展示）',
    source: '可学会子模型快照',
    role: 'input',
    usedBy: '与 S、W、G、τ 一起计算直接提分价值 D',
  },
  transfer_rate: {
    key: 'transfer_rate',
    symbol: 'τ',
    name: '迁移率',
    description: '迁移子模型对“学会后能在目标考试中正确应用”的估计，作为核心价值链的已计算输入。',
    formula: 'τ = 路径规划器保存的 transfer_rate（页面按百分比展示）',
    source: '迁移率子模型快照',
    role: 'input',
    usedBy: '与 S、W、G、L 一起计算直接提分价值 D',
  },
  knowledge_graph: {
    key: 'knowledge_graph',
    symbol: 'R, d',
    name: '知识图谱依赖数据',
    description: '记录知识点之间的前置关系、关系强度及沿依赖链到后继知识点的距离。',
    formula: 'R = 前置关系集合；rᵢⱼ = 当前边强度（最低按 0.05）；dᵢⱼ = 依赖距离（1～5）',
    source: '知识图谱前置关系与关系权重',
    role: 'input',
    usedBy: '与后继知识点直接提分 Dⱼ 一起计算解锁收益 Kᵢ',
  },
  unlock_gain: {
    key: 'unlock_gain',
    symbol: 'K',
    name: '后继解锁预计收益',
    description: '知识图谱子模型汇总的后继知识收益，作为核心边际价值公式的已计算输入。',
    formula: 'Kᵢ = Σⱼ[Dⱼ × Pᵢⱼ × 0.70^(dᵢⱼ-1)]；Pᵢⱼ = 沿路径各边归一化关系强度之积（最多 5 层）',
    source: '后继知识点直接提分 Dⱼ、知识图谱前置关系、关系强度 r、依赖距离 d',
    role: 'derived',
    usedBy: '与直接提分价值 D 一起计算战略价值 V',
  },
  estimated_minutes: {
    key: 'estimated_minutes',
    symbol: 'T',
    name: '预计学习时间',
    description: '时间成本子模型给出的本轮学习分钟数，作为边际价值分母。',
    formula: 'T = 路径节点保存的 estimated_minutes；计算时最小按 1 分钟',
    source: '学习时间子模型快照',
    role: 'derived',
    usedBy: '作为边际价值 MV 的时间成本分母',
  },
  effective_mastery: {
    key: 'effective_mastery',
    symbol: 'Mₑ',
    name: '有效掌握度',
    description: '可信度不足时，将当前掌握度向中性值50分收缩，避免过度相信少量证据。',
    formula: '有掌握度时：Mₑ = (C÷100)×M + (1-C÷100)×50；无掌握度时：Mₑ = 50',
    source: '当前掌握度 M、评估可信度 C',
    role: 'derived',
    usedBy: '与首轮目标掌握度 Mₜ 一起计算掌握度差距 G',
  },
  mastery_gap: {
    key: 'mastery_gap',
    symbol: 'G',
    name: '掌握度差距',
    description: '该知识点距离首轮规划目标还有多少可提升空间。',
    formula: 'G = max(0, Mₜ - Mₑ)',
    source: '首轮目标掌握度 Mₜ、有效掌握度 Mₑ',
    role: 'derived',
    usedBy: '与 S、W、L、τ 一起计算直接提分价值 D',
  },
  direct_gain: {
    key: 'direct_gain',
    symbol: 'D',
    name: '直接提分价值',
    description: '学习该知识点本身预计能带来的考试分数提升。',
    formula: 'D = S × (W÷100) × (G÷100) × (L÷100) × (τ÷100)',
    source: 'S、W、G、L、τ',
    role: 'derived',
    usedBy: '与后继解锁预计收益 K 一起计算战略价值 V',
  },
  strategic_value: {
    key: 'strategic_value',
    symbol: 'V',
    name: '战略价值',
    description: '只包含首轮直接提分与按固定权重 0.70 计入的后继解锁收益。',
    formula: 'V = D + 0.70 × K',
    source: '直接提分价值 D、后继解锁预计收益 K；0.70 为算法固定权重',
    role: 'derived',
    usedBy: '作为边际价值 MV 的价值分子',
  },
  marginal_value: {
    key: 'marginal_value',
    symbol: 'MV',
    name: '边际价值',
    description: '每投入一分钟能够获得的综合学习价值，是知识点价值排序的核心指标。',
    formula: 'MV = V ÷ max(T, 1)',
    source: '战略价值 V、预计学习时间 T',
    role: 'result',
    usedBy: '用于知识点价值排序；实际排期还要满足下方前置关系与时间容量约束',
  },
  daily_capacity: {
    ...DEFINITIONS.daily_capacity,
    role: 'input',
    usedBy: '仅用于路径容量约束，不进入边际价值 MV',
  },
  remaining_days: {
    ...DEFINITIONS.remaining_days,
    role: 'input',
    usedBy: '仅用于路径容量约束，不进入边际价值 MV',
  },
}

const FLOW_STAGES: FlowStage[] = [
  {
    key: 'raw',
    title: '① 原始与基础输入',
    subtitle: 'D、K、T 计算所需的基础数据',
    icon: <DatabaseOutlined />,
    indicators: [
      CHAIN_DEFINITIONS.current_mastery,
      CHAIN_DEFINITIONS.confidence,
      CHAIN_DEFINITIONS.target_mastery,
      CHAIN_DEFINITIONS.total_score,
      CHAIN_DEFINITIONS.exam_weight,
      CHAIN_DEFINITIONS.learnability,
      CHAIN_DEFINITIONS.transfer_rate,
      CHAIN_DEFINITIONS.knowledge_graph,
    ],
  },
  {
    key: 'processed',
    title: '② 中间参数',
    subtitle: '由第一步输入逐项计算',
    icon: <ApartmentOutlined />,
    indicators: [
      CHAIN_DEFINITIONS.effective_mastery,
      CHAIN_DEFINITIONS.mastery_gap,
      CHAIN_DEFINITIONS.direct_gain,
      CHAIN_DEFINITIONS.unlock_gain,
      CHAIN_DEFINITIONS.estimated_minutes,
    ],
  },
  {
    key: 'value',
    title: '③ 逐步计算结果',
    subtitle: 'V = D + 0.70 × K',
    icon: <RiseOutlined />,
    indicators: [
      CHAIN_DEFINITIONS.strategic_value,
    ],
  },
  {
    key: 'result',
    title: '④ 最终计算结果',
    subtitle: '战略价值除以预计学习时间',
    icon: <CalculatorOutlined />,
    indicators: [CHAIN_DEFINITIONS.marginal_value],
  },
]

const CORE_FLOW_STAGES: FlowStage[] = [
  {
    key: 'raw',
    title: '① 原始与基础输入',
    subtitle: 'D、K、T 的计算依据；旧路径缺失项会显示暂无',
    icon: <DatabaseOutlined />,
    indicators: [
      CHAIN_DEFINITIONS.current_mastery,
      CHAIN_DEFINITIONS.confidence,
      CHAIN_DEFINITIONS.target_mastery,
      CHAIN_DEFINITIONS.total_score,
      CHAIN_DEFINITIONS.exam_weight,
      CHAIN_DEFINITIONS.learnability,
      CHAIN_DEFINITIONS.transfer_rate,
      CHAIN_DEFINITIONS.knowledge_graph,
    ],
  },
  {
    key: 'processed',
    title: '② 中间参数',
    subtitle: '由第一步输入及知识图谱计算',
    icon: <ApartmentOutlined />,
    indicators: [
      CHAIN_DEFINITIONS.effective_mastery,
      CHAIN_DEFINITIONS.mastery_gap,
      CHAIN_DEFINITIONS.direct_gain,
      CHAIN_DEFINITIONS.unlock_gain,
      CHAIN_DEFINITIONS.estimated_minutes,
    ],
  },
  {
    key: 'value',
    title: '③ 战略价值',
    subtitle: 'V = D + 0.70 × K',
    icon: <RiseOutlined />,
    indicators: [CHAIN_DEFINITIONS.strategic_value],
  },
  {
    key: 'result',
    title: '④ 最终计算结果',
    subtitle: '只使用左侧 V 和输入 T',
    icon: <CalculatorOutlined />,
    indicators: [CHAIN_DEFINITIONS.marginal_value],
  },
]

const ROLE_META = {
  input: { label: '计算输入', color: 'green' },
  derived: { label: '中间结果', color: 'blue' },
  result: { label: '最终结果', color: 'purple' },
} as const

const ESTIMATION_STATUS = {
  ready: { label: '历史样本充足', color: 'success' },
  limited: { label: '历史样本较少', color: 'warning' },
  unavailable: { label: '使用模型基线', color: 'default' },
} as const

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

export default function MarginalValueAnalytics() {
  const [students, setStudents] = useState<StudentOption[]>([])
  const [studentId, setStudentId] = useState<number>()
  const [knowledgeOptions, setKnowledgeOptions] = useState<KnowledgeDirectoryOptions | null>(null)
  const [knowledgeScope, setKnowledgeScope] = useState<KnowledgeScopeParams>({})
  const [data, setData] = useState<MarginalValueAnalysisResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedKey, setSelectedKey] = useState<string>()

  const loadData = useCallback(async (id: number, scope: KnowledgeScopeParams = {}) => {
    setLoading(true)
    try {
      const response = await analyticsApi.getMarginalValue(id, scope)
      setData(response.data)
    } catch {
      message.error('边际价值分析数据加载失败')
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
  const visibleSampleCount = Math.min(data?.summary.node_count ?? 0, 12)
  const hasDetailedSnapshot = Boolean(
    visibleSampleCount
      && ['total_score', 'learnability', 'transfer_rate'].every(
        key => (metricMap.get(key)?.sample_size ?? 0) === visibleSampleCount,
      ),
  )
  const flowStages = hasDetailedSnapshot ? FLOW_STAGES : CORE_FLOW_STAGES
  const selectedDefinition = selectedKey
    ? (
        flowStages
          .flatMap(stage => stage.indicators)
          .find(indicator => indicator.key === selectedKey)
        ?? CHAIN_DEFINITIONS[selectedKey]
      )
    : undefined
  const selectedMetric = selectedKey ? metricMap.get(selectedKey) : undefined
  const support = data?.supporting_statistics
  const emptyMasteryBuckets = ['0–19', '20–39', '40–59', '60–79', '80–100']
    .map(label => ({ label, value: null, sample_size: 0 }))
  const supportCharts: NodeMetricBarGroup[] = selectedKey === 'learnability'
    ? [
        {
          title: support?.learnability.model_inputs?.length
            ? '当前模型输入与输出'
            : '认知层级基线与修正规则',
          description: support?.learnability.model_inputs?.length
            ? '展示当前路径节点在规则模型中的平均基线、近期表现修正和最终输出。'
            : '当前路径缺少新版统计快照，以下展示算法实际采用的认知层级基线；连续表现修正在公式区说明。',
          primaryLabel: support?.learnability.model_inputs?.length ? '当前路径均值' : '算法基线',
          rows: (support?.learnability.model_inputs?.length
            ? support.learnability.model_inputs
            : [
                { label: '运用/应用', value: 55, sample_size: 0 },
                { label: '掌握', value: 65, sample_size: 0 },
                { label: '理解', value: 75, sample_size: 0 },
                { label: '其它层级', value: 85, sample_size: 0 },
              ]).map(point => ({
            label: point.label,
            value: point.value,
            unit: '%',
            note: point.sample_size ? `路径节点 ${point.sample_size} 个` : '固定规则基线',
          })),
        },
        {
          title: '历史学习成功率',
          description: support?.learnability.note ?? '暂无历史统计说明',
          primaryLabel: '成功率',
          rows: (support?.learnability.success_by_prior_mastery ?? emptyMasteryBuckets).map(point => ({
            label: `学习前掌握度 ${point.label}`,
            value: point.value,
            unit: '%',
            note: `有效学习样本 ${point.sample_size} 次`,
          })),
        },
      ]
    : selectedKey === 'estimated_minutes'
      ? [
        {
            title: support?.estimated_minutes.model_inputs?.length
              ? '当前时间模型输入与输出'
              : '认知层级基准时长',
            description: support?.estimated_minutes.model_inputs?.length
              ? '展示认知层级基准时长、当前掌握差距和最终预计学习时间。'
              : '当前路径缺少新版统计快照，以下展示时间模型采用的认知层级固定基准。',
            primaryLabel: support?.estimated_minutes.model_inputs?.length ? '当前路径均值' : '算法基准',
            rows: (support?.estimated_minutes.model_inputs?.length
              ? support.estimated_minutes.model_inputs
              : [
                  { label: '其它层级', value: 25, sample_size: 0 },
                  { label: '理解', value: 40, sample_size: 0 },
                  { label: '掌握', value: 55, sample_size: 0 },
                  { label: '运用/应用', value: 75, sample_size: 0 },
                ]).map(point => ({
              label: point.label,
              value: point.value,
              unit: point.label === '掌握度差距' ? '%' : '分钟',
              note: point.sample_size ? `路径节点 ${point.sample_size} 个` : '固定规则基准',
            })),
          },
          {
            title: '历史实际学习时长',
            description: support?.estimated_minutes.note ?? '暂无历史统计说明',
            primaryLabel: '平均时长',
            rows: (support?.estimated_minutes.duration_by_prior_mastery ?? emptyMasteryBuckets).map(point => ({
              label: `学习前掌握度 ${point.label}`,
              value: point.value,
              unit: '分钟',
              note: `有效时长样本 ${point.sample_size} 次`,
            })),
          },
        ]
      : []
  const supportFormula = selectedKey === 'learnability'
    ? support?.learnability.formula
      ?? 'L = clamp(认知层级基线 + min(连续答对, 2)×4% - min(连续答错, 2)×5%, 35%, 90%)'
    : selectedKey === 'estimated_minutes'
      ? support?.estimated_minutes.formula
        ?? 'T = clamp(认知层级基准时长 × (0.65 + 掌握差距) × [1 + 0.25×(1-可信度)], 20, 120)'
      : undefined

  const changeScope = (scope: KnowledgeScopeParams) => {
    setKnowledgeScope(scope)
    if (studentId) void loadData(studentId, scope)
  }

  return (
    <div className="marginal-analysis-page">
      <div className="analytics-page-header">
        <div>
          <h1><CalculatorOutlined />边际价值计算指标分析</h1>
          <p className="marginal-analysis-purpose">
            路径规划算法中的边际价值计算相关指标分析。提分空间大、学习时间短的知识点优先学习。
          </p>
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
          <section className="marginal-estimation-board">
            <div className="marginal-estimation-heading">
              <div>
                <h2>关键指标的历史统计估计过程</h2>
                <p>
                  D、K、T 不是可以直接读取的原始数据。系统先分析历史行为和模型参数得到估计值，
                  再把结果保存到路径快照，供后续计算 V 和 MV。
                </p>
              </div>
              <Tag color="blue">历史数据 → 模型估计 → 路径快照</Tag>
            </div>
            <div className="marginal-estimation-cards">
              {(data.estimation_evidence ?? []).map(item => {
                const status = ESTIMATION_STATUS[item.status]
                return (
                  <article className="marginal-estimation-card" key={item.key}>
                    <header>
                      <div>
                        <span>{item.symbol}</span>
                        <strong>{item.name}</strong>
                      </div>
                      <Tag color={status.color}>{status.label}</Tag>
                    </header>
                    <div className="marginal-estimation-value">
                      <em>
                        {item.current_mean == null
                          ? '暂无估计'
                          : `${item.current_mean.toFixed(3)}${item.unit}`}
                      </em>
                      <small>{item.estimation_type}</small>
                    </div>
                    <code>{item.formula}</code>
                    <div className="marginal-estimation-inputs">
                      <div>
                        <b>历史统计输入</b>
                        <ul>
                          {item.history_inputs.map(input => <li key={input}>{input}</li>)}
                        </ul>
                      </div>
                      <div>
                        <b>模型与结构输入</b>
                        <ul>
                          {item.model_inputs.map(input => <li key={input}>{input}</li>)}
                        </ul>
                      </div>
                    </div>
                    <footer>
                      <span>
                        有效证据：<strong>{item.sample_size}</strong> {item.sample_label}
                      </span>
                      <p>{item.snapshot_note}</p>
                    </footer>
                  </article>
                )
              })}
            </div>
          </section>

          <section className="marginal-flow-board">
            <div className="marginal-formula">
              <span>MV 边际价值</span>
              <strong>=</strong>
              <span>V 战略价值</span>
              <strong>÷</strong>
              <span>max(T 预计学习时间, 1)</span>
              <i>其中 V = D + 0.70 × K（0.70 为算法固定权重）</i>
            </div>
            <div className={`marginal-flow marginal-flow-${flowStages.length}`}>
              {flowStages.map((stage, index) => (
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
                      {stage.indicators.map(indicator => {
                        const metric = metricMap.get(indicator.key)
                        return (
                          <button
                            type="button"
                            className={`marginal-indicator diagnostic-indicator diagnostic-role-${indicator.role}`}
                            key={indicator.key}
                            onClick={() => setSelectedKey(indicator.key)}
                          >
                            <span>
                              <span className="diagnostic-indicator-title">
                                <strong>{indicator.symbol ? `${indicator.symbol} · ` : ''}{indicator.name}</strong>
                                {indicator.role && (
                                  <Tag color={ROLE_META[indicator.role].color}>
                                    {ROLE_META[indicator.role].label}
                                  </Tag>
                                )}
                              </span>
                              <small className="diagnostic-indicator-used-by">
                                {indicator.role === 'input'
                                  ? `用于：${indicator.usedBy}`
                                  : `公式：${indicator.formula}`}
                              </small>
                            </span>
                            <em>{formatMetric(metric)}</em>
                          </button>
                        )
                      })}
                    </div>
                  </article>
                  {index < flowStages.length - 1 && (
                    <div className="marginal-flow-arrow"><RightOutlined /></div>
                  )}
                </div>
              ))}
            </div>
            <div className="marginal-constraints">
              <span><InfoCircleOutlined /> 排期约束（不改变知识点自身边际价值）</span>
              {[CHAIN_DEFINITIONS.daily_capacity, CHAIN_DEFINITIONS.remaining_days].map(indicator => (
                <button
                  type="button"
                  key={indicator.key}
                  onClick={() => setSelectedKey(indicator.key)}
                >
                  {indicator.name}：<strong>{formatMetric(metricMap.get(indicator.key))}</strong>
                </button>
              ))}
            </div>
          </section>
        </>
      ) : (
        <Empty description="该学生尚未生成学习路径，暂无边际价值计算结果" />
      )}

      <Drawer
        width={760}
        open={Boolean(selectedDefinition)}
        title={selectedDefinition
          ? `${selectedDefinition.symbol ? `${selectedDefinition.symbol} · ` : ''}${selectedDefinition.name}`
          : undefined}
        onClose={() => setSelectedKey(undefined)}
      >
        {selectedDefinition && (
          <div className="marginal-metric-detail">
            <Alert type="info" showIcon message={selectedDefinition.description} />
            <Descriptions bordered column={1} size="small">
              {selectedDefinition.role && (
                <Descriptions.Item label="链路角色">
                  <Tag color={ROLE_META[selectedDefinition.role].color}>
                    {ROLE_META[selectedDefinition.role].label}
                  </Tag>
                </Descriptions.Item>
              )}
              <Descriptions.Item label="数据来源">{selectedDefinition.source}</Descriptions.Item>
              <Descriptions.Item label="计算公式">
                <code>{selectedDefinition.formula}</code>
              </Descriptions.Item>
              <Descriptions.Item label="下游用途">{selectedDefinition.usedBy}</Descriptions.Item>
              <Descriptions.Item label="当前路径均值">
                <Tag color="cyan">{formatMetric(selectedMetric)}</Tag>
              </Descriptions.Item>
            </Descriptions>
            {supportFormula && (
              <section className="marginal-support-formula">
                <h3>核心计算逻辑</h3>
                <code>{supportFormula}</code>
              </section>
            )}
            {supportCharts.length > 0 && (
              <div className="node-metric-chart-list">
                {supportCharts.map(group => (
                  <NodeMetricBarChart group={group} key={group.title} />
                ))}
              </div>
            )}
          </div>
        )}
      </Drawer>
    </div>
  )
}

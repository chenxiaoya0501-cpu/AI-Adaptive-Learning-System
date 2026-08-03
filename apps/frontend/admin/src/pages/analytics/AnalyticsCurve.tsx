import { Empty, Tag, Tooltip } from 'antd'
import {
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  MinusCircleOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons'
import type { AnalyticsParameter } from '../../api'

const AXIS_LABELS: Record<string, { x: string; y: string }> = {
  learning_duration: {
    x: '学习前掌握度区间',
    y: '平均实际学习时间（分钟）',
  },
  mastery_gain: {
    x: '学习前掌握度区间',
    y: '平均掌握度提升（分）',
  },
  difficulty_accuracy: {
    x: '题目难度等级（1～5）',
    y: '对应难度题目正确率（%）',
  },
  learning_success: {
    x: '学习前掌握度区间',
    y: '达到目标掌握度的比例（%）',
  },
  mastery_growth: {
    x: '已完成有效练习题数量',
    y: '对应题量下的平均掌握度（分）',
  },
  transfer_rate: {
    x: '课程同步时的掌握度区间',
    y: '后续正式测评正确率（%）',
  },
  forgetting: {
    x: '同一知识点两次作答的时间间隔',
    y: '间隔后再次作答的正确率（%）',
  },
  prerequisite_impact: {
    x: '前置知识表现分组',
    y: '后续知识点正确率（%）',
  },
  mastery_trajectory: {
    x: '有效练习题序号',
    y: '每题提交后掌握度（分）',
  },
  confidence: {
    x: '已完成有效练习题数量',
    y: '掌握度评估可信度（%）',
  },
  ability_accuracy: {
    x: '题库标注的能力维度',
    y: '该能力维度题目正确率（%）',
  },
  recent_streak: {
    x: '答题顺序',
    y: '连续表现（正数答对、负数答错）',
  },
  reinforcement_gain: {
    x: '强化学习轮次',
    y: '每轮掌握度提升（分）',
  },
  daily_capacity: {
    x: '学习目标或目标创建日期',
    y: '每日可投入学习时间（分钟）',
  },
}

const STATUS = {
  ready: {
    color: 'success',
    text: '样本充足',
    icon: <CheckCircleOutlined />,
  },
  limited: {
    color: 'warning',
    text: '样本较少',
    icon: <ExclamationCircleOutlined />,
  },
  unavailable: {
    color: 'default',
    text: '暂无数据',
    icon: <MinusCircleOutlined />,
  },
} as const

function formatValue(value: number, unit: string) {
  const digits = Math.abs(value) >= 10 ? 1 : 2
  return `${value.toFixed(digits)}${unit}`
}

function truncateAxisLabel(label: string, maxCharacters: number) {
  const characters = Array.from(label)
  if (characters.length <= maxCharacters) return label
  return `${characters.slice(0, Math.max(1, maxCharacters - 1)).join('')}…`
}

function buildXAxisTickIndexes(pointCount: number, maxTicks: number) {
  if (pointCount <= maxTicks) {
    return new Set(Array.from({ length: pointCount }, (_, index) => index))
  }

  return new Set(
    Array.from(
      { length: maxTicks },
      (_, index) => Math.round((index * (pointCount - 1)) / (maxTicks - 1)),
    ),
  )
}

export default function AnalyticsCurve({
  parameter,
  xAxisLabel,
  yAxisLabel,
}: {
  parameter: AnalyticsParameter
  xAxisLabel?: string
  yAxisLabel?: string
}) {
  const valid = parameter.curve
    .map((point, index) => ({ ...point, index }))
    .filter((point): point is typeof point & { value: number } => typeof point.value === 'number')
  const status = STATUS[parameter.status]

  const axes = AXIS_LABELS[parameter.key] ?? {
    x: '统计分组',
    y: `${parameter.name}${parameter.unit ? `（${parameter.unit}）` : ''}`,
  }
  const resolvedXAxis = xAxisLabel ?? axes.x
  const resolvedYAxis = yAxisLabel ?? axes.y

  const width = 620
  const height = 270
  const padding = { left: 72, right: 24, top: 24, bottom: 70 }
  const plotWidth = width - padding.left - padding.right
  const plotHeight = height - padding.top - padding.bottom

  const rawValues = valid.map(point => point.value)
  const minimum = rawValues.length ? Math.min(...rawValues, 0) : 0
  const maximum = rawValues.length ? Math.max(...rawValues, 1) : 1
  const span = Math.max(1, maximum - minimum)
  const lower = minimum - span * 0.08
  const upper = maximum + span * 0.12
  const domain = Math.max(1, upper - lower)
  const count = Math.max(parameter.curve.length, 2)
  const xOf = (index: number) => padding.left + (index / (count - 1)) * plotWidth
  const yOf = (value: number) => padding.top + ((upper - value) / domain) * plotHeight
  const polyline = valid.map(point => `${xOf(point.index)},${yOf(point.value)}`).join(' ')
  const maxLabelCharacters = parameter.curve.length <= 4 ? 12 : 8
  const longestLabelCharacters = Math.max(
    0,
    ...parameter.curve.map(point => Array.from(point.label).length),
  )
  const estimatedTickWidth =
    Math.min(longestLabelCharacters, maxLabelCharacters) * 12 + 16
  const maxXAxisTicks = Math.min(
    parameter.curve.length,
    Math.max(3, Math.min(6, Math.floor(plotWidth / Math.max(1, estimatedTickWidth)) + 1)),
  )
  const xAxisTickIndexes = buildXAxisTickIndexes(parameter.curve.length, maxXAxisTicks)
  const isXAxisCondensed = parameter.curve.length > maxXAxisTicks

  return (
    <section className="analytics-curve-card">
      <div className="analytics-curve-header">
        <div>
          <div className="analytics-curve-title">
            {parameter.name}
            <Tooltip title={parameter.description}>
              <QuestionCircleOutlined className="analytics-help-icon" />
            </Tooltip>
          </div>
          <div className="analytics-curve-description">{parameter.description}</div>
        </div>
        <Tag color={status.color} icon={status.icon}>{status.text}</Tag>
      </div>

      {valid.length ? (
        <div className="analytics-chart-wrap">
          <svg
            className="analytics-chart"
            viewBox={`0 0 ${width} ${height}`}
            role="img"
            aria-label={`${parameter.name}曲线`}
          >
            {[0, 1, 2, 3, 4].map(index => {
              const y = padding.top + (index / 4) * plotHeight
              const value = upper - (index / 4) * domain
              return (
                <g key={index}>
                  <line
                    x1={padding.left}
                    y1={y}
                    x2={width - padding.right}
                    y2={y}
                    stroke="#edf2f1"
                  />
                  <text x={padding.left - 10} y={y + 4} textAnchor="end" className="chart-axis-label">
                    {Math.round(value)}
                  </text>
                </g>
              )
            })}
            {parameter.curve.map((point, index) => (
              xAxisTickIndexes.has(index) ? (
                <text
                  key={`${point.label}-${index}`}
                  x={xOf(index)}
                  y={height - 40}
                  textAnchor={
                    index === 0
                      ? 'start'
                      : index === parameter.curve.length - 1
                        ? 'end'
                        : 'middle'
                  }
                  className="chart-axis-label chart-x-axis-label"
                >
                  <title>{point.label}</title>
                  {truncateAxisLabel(point.label, maxLabelCharacters)}
                </text>
              ) : null
            ))}
            {valid.length > 1 && (
              <polyline
                points={polyline}
                fill="none"
                stroke="#11877a"
                strokeWidth="3"
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            )}
            {valid.map(point => (
              <g key={`${point.label}-${point.index}`}>
                <circle
                  cx={xOf(point.index)}
                  cy={yOf(point.value)}
                  r="5"
                  fill="#fff"
                  stroke="#11877a"
                  strokeWidth="3"
                />
                <title>
                  {point.label}：{formatValue(point.value, parameter.unit)}，样本 {point.sample_size}
                </title>
              </g>
            ))}
            <text
              x={padding.left + plotWidth / 2}
              y={height - 8}
              textAnchor="middle"
              className="chart-axis-title"
            >
              横坐标：{resolvedXAxis}
            </text>
            <text
              x={16}
              y={padding.top + plotHeight / 2}
              textAnchor="middle"
              className="chart-axis-title"
              transform={`rotate(-90 16 ${padding.top + plotHeight / 2})`}
            >
              纵坐标：{resolvedYAxis}
            </text>
          </svg>
        </div>
      ) : (
        <div className="analytics-empty">
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚无可计算的历史记录" />
        </div>
      )}

      <div className="analytics-axis-explanation">
        <span><b>横坐标</b>{resolvedXAxis}</span>
        <span><b>纵坐标</b>{resolvedYAxis}</span>
        {isXAxisCondensed && (
          <span className="analytics-axis-hint">
            横轴标签已间隔展示，悬停标签或数据点可查看完整名称
          </span>
        )}
      </div>
      <div className="analytics-curve-footer">
        <span>单位：{parameter.unit}</span>
        <span>有效样本：{parameter.sample_size}</span>
        {parameter.note && <span className="analytics-note">{parameter.note}</span>}
      </div>
    </section>
  )
}

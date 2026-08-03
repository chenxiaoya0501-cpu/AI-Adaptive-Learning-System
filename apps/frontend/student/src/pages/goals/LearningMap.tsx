import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert,
  Button,
  Empty,
  Segmented,
  Select,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import {
  ArrowLeftOutlined,
  MinusOutlined,
  PlusOutlined,
  ReloadOutlined,
  UndoOutlined,
  CompassOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import {
  goalsApi,
  type LearningMapData,
  type LearningMapEdge,
  type LearningMapNode,
} from '../../api/goals'
import { ExamQuestionBody } from '../../components/RichQuestionContent'
import './learningMap.css'

type PositionedNode = LearningMapNode & { x: number; y: number }

function scoreLevel(score: number): 'l1' | 'l2' | 'l3' | 'l4' | 'l5' | 'l6' {
  if (score <= 20) return 'l1'
  if (score <= 40) return 'l2'
  if (score < 60) return 'l3'
  if (score < 75) return 'l4'
  if (score < 90) return 'l5'
  return 'l6'
}

function questionScorePercent(node: LearningMapNode) {
  if (typeof node.score_percent === 'number') return node.score_percent
  const fullScore = Number(node.score || 0)
  if (fullScore <= 0) return 0
  return Math.min(100, Math.max(0, Number(node.score_got || 0) / fullScore * 100))
}

function formatTestTime(value?: string | null) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

const TYPE_LABELS: Record<string, string> = {
  choice: '选择题',
  fill: '填空题',
  answer: '解答题',
  proof: '证明题',
}

function errorText(error: any) {
  return error?.response?.data?.detail || '学习地图加载失败'
}

function layoutGraph(nodes: LearningMapNode[], edges: LearningMapEdge[]) {
  if (!nodes.length) {
    return { nodes: [] as PositionedNode[], width: 1040, height: 620 }
  }
  const knowledge = nodes.filter((node) => node.node_type === 'knowledge')
  const questions = nodes.filter((node) => node.node_type === 'question')
  const kpIds = new Set(knowledge.map((node) => node.id))
  const prerequisite = edges.filter(
    (edge) =>
      edge.type === 'prerequisite' && kpIds.has(edge.source) && kpIds.has(edge.target),
  )
  const indegree = new Map(knowledge.map((node) => [node.id, 0]))
  const next = new Map(knowledge.map((node) => [node.id, [] as string[]]))
  prerequisite.forEach((edge) => {
    indegree.set(edge.target, (indegree.get(edge.target) || 0) + 1)
    next.get(edge.source)?.push(edge.target)
  })

  const layer = new Map(knowledge.map((node) => [node.id, 0]))
  const queue = knowledge.filter((node) => indegree.get(node.id) === 0).map((node) => node.id)
  for (let index = 0; index < queue.length; index += 1) {
    const current = queue[index]
    for (const target of next.get(current) || []) {
      layer.set(target, Math.max(layer.get(target) || 0, (layer.get(current) || 0) + 1))
      indegree.set(target, (indegree.get(target) || 1) - 1)
      if (indegree.get(target) === 0) queue.push(target)
    }
  }

  const questionEdges = edges.filter((edge) => edge.type === 'question')
  questions.forEach((question) => {
    const sources = questionEdges
      .filter((edge) => edge.target === question.id)
      .map((edge) => layer.get(edge.source) || 0)
    layer.set(question.id, (sources.length ? Math.max(...sources) : 0) + 1)
  })

  const width = Math.max(1280, Math.min(1900, 900 + Math.sqrt(nodes.length) * 82))
  const height = Math.max(820, Math.min(1320, 620 + Math.sqrt(nodes.length) * 54))
  const centerX = width / 2
  const centerY = height / 2
  const hash = (value: string) => {
    let result = 2166136261
    for (let index = 0; index < value.length; index += 1) {
      result ^= value.charCodeAt(index)
      result = Math.imul(result, 16777619)
    }
    return result >>> 0
  }
  const adjacency = new Map(nodes.map((node) => [node.id, new Set<string>()]))
  edges.forEach((edge) => {
    if (!adjacency.has(edge.source) || !adjacency.has(edge.target)) return
    adjacency.get(edge.source)?.add(edge.target)
    adjacency.get(edge.target)?.add(edge.source)
  })
  const nodeById = new Map(nodes.map((node) => [node.id, node]))
  const unvisited = new Set(nodes.map((node) => node.id))
  const components: string[][] = []
  while (unvisited.size) {
    const start = unvisited.values().next().value as string
    const queue = [start]
    const component: string[] = []
    unvisited.delete(start)
    for (let index = 0; index < queue.length; index += 1) {
      const current = queue[index]
      component.push(current)
      for (const neighbor of adjacency.get(current) || []) {
        if (!unvisited.has(neighbor)) continue
        unvisited.delete(neighbor)
        queue.push(neighbor)
      }
    }
    components.push(component)
  }
  components.sort((a, b) => b.length - a.length)

  const initialPositions = new Map<
    string,
    { x: number; y: number; anchorX: number; anchorY: number }
  >()
  const satelliteCount = Math.max(1, components.length - 1)
  components.forEach((component, componentIndex) => {
    const orbit = componentIndex === 0 ? 0 : Math.ceil(componentIndex / 8)
    const orbitIndex = componentIndex === 0 ? 0 : componentIndex - 1
    const orbitSlots = Math.min(8 * orbit, satelliteCount)
    const componentAngle =
      componentIndex === 0
        ? 0
        : (Math.PI * 2 * (orbitIndex % orbitSlots)) / orbitSlots -
          Math.PI / 2 +
          orbit * 0.19
    const componentCenter =
      componentIndex === 0
        ? { x: centerX, y: centerY }
        : {
            x: centerX + Math.cos(componentAngle) * (220 + orbit * 135),
            y: centerY + Math.sin(componentAngle) * (155 + orbit * 95),
          }
    const hub = [...component].sort(
      (a, b) =>
        (adjacency.get(b)?.size || 0) - (adjacency.get(a)?.size || 0) ||
        a.localeCompare(b),
    )[0]
    const levels = new Map([[hub, 0]])
    const queue = [hub]
    for (let index = 0; index < queue.length; index += 1) {
      const current = queue[index]
      const neighbors = [...(adjacency.get(current) || [])].sort()
      for (const neighbor of neighbors) {
        if (!component.includes(neighbor) || levels.has(neighbor)) continue
        levels.set(neighbor, (levels.get(current) || 0) + 1)
        queue.push(neighbor)
      }
    }
    const byLevel = new Map<number, string[]>()
    component.forEach((id) => {
      const levelValue = levels.get(id) || 0
      byLevel.set(levelValue, [...(byLevel.get(levelValue) || []), id])
    })
    byLevel.forEach((ids, levelValue) => {
      ids.sort()
      ids.forEach((id, index) => {
        if (levelValue === 0) {
          initialPositions.set(id, {
            x: componentCenter.x,
            y: componentCenter.y,
            anchorX: componentCenter.x,
            anchorY: componentCenter.y,
          })
          return
        }
        const angleOffset = ((hash(hub) % 360) / 180) * Math.PI
        const angle = angleOffset + (Math.PI * 2 * index) / ids.length
        const radius = 105 * levelValue + Math.min(55, ids.length * 3)
        initialPositions.set(id, {
          x: componentCenter.x + Math.cos(angle) * radius,
          y: componentCenter.y + Math.sin(angle) * radius * 0.78,
          anchorX: componentCenter.x,
          anchorY: componentCenter.y,
        })
      })
    })
  })

  const points = nodes.map((node, index) => {
    const initial = initialPositions.get(node.id) || {
      x: centerX,
      y: centerY,
      anchorX: centerX,
      anchorY: centerY,
    }
    return {
      node,
      ...initial,
      vx: 0,
      vy: 0,
      index,
    }
  })
  const pointMap = new Map(points.map((point) => [point.node.id, point]))
  const graphEdges = edges
    .map((edge) => ({
      edge,
      source: pointMap.get(edge.source),
      target: pointMap.get(edge.target),
    }))
    .filter((row) => row.source && row.target)

  // 确定性力导向布局：斥力防重叠，弹簧力表达关系，同类节点形成自然簇。
  for (let iteration = 0; iteration < 280; iteration += 1) {
    const cooling = 1 - iteration / 320
    for (let i = 0; i < points.length; i += 1) {
      for (let j = i + 1; j < points.length; j += 1) {
        const a = points[i]
        const b = points[j]
        let dx = b.x - a.x
        let dy = b.y - a.y
        if (dx === 0 && dy === 0) {
          dx = ((hash(`${a.node.id}:${b.node.id}`) % 20) - 10) / 10
          dy = 1
        }
        const distanceSquared = Math.max(100, dx * dx + dy * dy)
        const distance = Math.sqrt(distanceSquared)
        const force = Math.min(3.6, 6200 / distanceSquared) * cooling
        const fx = (dx / distance) * force
        const fy = (dy / distance) * force
        a.vx -= fx
        a.vy -= fy
        b.vx += fx
        b.vy += fy
        if (distance < 78) {
          const collision = (78 - distance) * 0.055
          a.vx -= (dx / distance) * collision
          a.vy -= (dy / distance) * collision
          b.vx += (dx / distance) * collision
          b.vy += (dy / distance) * collision
        }
      }
    }
    graphEdges.forEach(({ edge, source, target }) => {
      if (!source || !target) return
      const dx = target.x - source.x
      const dy = target.y - source.y
      const distance = Math.max(1, Math.sqrt(dx * dx + dy * dy))
      const desired = edge.type === 'question' ? 92 : edge.type === 'related' ? 130 : 118
      const force = (distance - desired) * 0.007 * cooling
      const fx = (dx / distance) * force
      const fy = (dy / distance) * force
      source.vx += fx
      source.vy += fy
      target.vx -= fx
      target.vy -= fy
    })
    points.forEach((point) => {
      point.vx += (point.anchorX - point.x) * 0.0012 * cooling
      point.vy += (point.anchorY - point.y) * 0.0012 * cooling
      point.vx += (centerX - point.x) * 0.00045
      point.vy += (centerY - point.y) * 0.00045
      point.vx *= 0.82
      point.vy *= 0.82
      point.x += point.vx
      point.y += point.vy
    })
  }

  // 只平移、不压缩节点间距；图谱较大时扩展画布并通过滚动查看。
  const minX = Math.min(...points.map((point) => point.x))
  const maxX = Math.max(...points.map((point) => point.x))
  const minY = Math.min(...points.map((point) => point.y))
  const maxY = Math.max(...points.map((point) => point.y))
  const spanX = Math.max(1, maxX - minX)
  const spanY = Math.max(1, maxY - minY)
  const paddingX = 100
  const paddingY = 90
  const canvasWidth = Math.max(width, spanX + paddingX * 2)
  const canvasHeight = Math.max(height, spanY + paddingY * 2)
  const offsetX = (canvasWidth - spanX) / 2
  const offsetY = (canvasHeight - spanY) / 2
  const positioned: PositionedNode[] = points.map((point) => ({
    ...point.node,
    x: Math.round((offsetX + point.x - minX) * 10) / 10,
    y: Math.round((offsetY + point.y - minY) * 10) / 10,
  }))
  return {
    nodes: positioned,
    width: canvasWidth,
    height: canvasHeight,
  }
}

function nodeClass(node: LearningMapNode, selected: boolean) {
  const level =
    node.node_type === 'knowledge'
      ? ` mastery-${node.mastery_level || 'l0'}`
      : ` score-${node.score_level || scoreLevel(questionScorePercent(node))}`
  return `map-node map-node--${node.node_type} is-${node.status}${level}${
    selected ? ' is-selected' : ''
  }`
}

function statusText(node: LearningMapNode) {
  if (node.node_type === 'question') {
    if (node.view_scope === 'summary') {
      return `多次作答加权得分率 ${Math.round(questionScorePercent(node))}%`
    }
    if (node.status === 'correct') return '回答正确'
    if (node.status === 'partial') return `部分得分（${Math.round(node.score_percent || 0)}%）`
    return '回答错误'
  }
  if (node.status === 'mastered') return '已掌握'
  if (node.status === 'unmastered') return '未掌握'
  if (node.status === 'uncertain') return '掌握程度不明确'
  return '尚未测评'
}

function MapNodeText({ node }: { node: LearningMapNode }) {
  if (node.node_type === 'question') {
    const label = node.label.length > 6 ? `${node.label.slice(0, 6)}…` : node.label
    return (
      <text textAnchor="middle" className="map-node__qtext">
        <tspan x="0" dy="-1">
          {label}
        </tspan>
        <tspan x="0" dy="12" className="map-node__sub">
          {node.view_scope === 'summary'
            ? `${Math.round(questionScorePercent(node))}% · ${node.attempt_count || 1}次`
            : `${node.score_got || 0}/${node.score || 0}`}
        </tspan>
      </text>
    )
  }

  const lines =
    node.label.length <= 4
      ? [node.label]
      : [node.label.slice(0, 4), `${node.label.slice(4, 7)}${node.label.length > 7 ? '…' : ''}`]

  return (
    <text textAnchor="middle">
      {lines.map((line, index) => (
        <tspan
          key={`${node.id}-label-${index}`}
          x="0"
          dy={index === 0 ? (lines.length === 1 ? '-3' : '-9') : '11'}
        >
          {line}
        </tspan>
      ))}
      <tspan x="0" dy="12" className="map-node__sub">
        {node.mastery_score == null ? '未测' : `${Math.round(node.mastery_score)}/100`}
      </tspan>
    </text>
  )
}

function DetailPanel({
  node,
  nodeMap,
  edges,
  onSelectNode,
  visibleHistoryIds,
  fixedHistoryIds,
  onToggleHistoryNode,
}: {
  node: LearningMapNode | null
  nodeMap: Map<string, LearningMapNode>
  edges: LearningMapEdge[]
  onSelectNode: (nodeId: string) => void
  visibleHistoryIds: Set<string>
  fixedHistoryIds: Set<string>
  onToggleHistoryNode: (nodeId: string, visible: boolean) => void
}) {
  if (!node) return <Empty description="点击左侧节点查看详情" />
  const incoming = edges
    .filter((edge) => edge.target === node.id && edge.type === 'prerequisite')
    .map((edge) => nodeMap.get(edge.source))
    .filter(Boolean) as LearningMapNode[]
  const outgoing = edges
    .filter((edge) => edge.source === node.id && edge.type === 'prerequisite')
    .map((edge) => nodeMap.get(edge.target))
    .filter(Boolean) as LearningMapNode[]
  const linked = edges
    .filter(
      (edge) =>
        edge.type === 'question' &&
        (edge.source === node.id || edge.target === node.id),
    )
    .map((edge) => nodeMap.get(edge.source === node.id ? edge.target : edge.source))
    .filter(Boolean) as LearningMapNode[]
  const linkedAttempts = linked.filter(
    (linkedNode) =>
      linkedNode.node_type === 'question' &&
      linkedNode.view_scope !== 'summary',
  )

  return (
    <div className="map-detail">
      <div className="map-detail__type">
        {node.node_type === 'knowledge' ? '知识点详情' : '题目详情'}
      </div>
      <Typography.Title level={4}>{node.label}</Typography.Title>
      <Tag className={`map-status-tag is-${node.status}`}>{statusText(node)}</Tag>

      {node.node_type === 'knowledge' ? (
        <>
          <div className={`map-detail__mastery mastery-${node.mastery_level || 'l0'}`}>
            <div className="map-detail__mastery-main">
              <strong>
                {node.mastery_score == null ? '--' : Math.round(node.mastery_score)}
              </strong>
              <span>/100 掌握分</span>
            </div>
            <div className="map-detail__mastery-sub">
              <span>置信度 <strong>{Math.round((node.confidence || 0) * 100)}%</strong></span>
              <span>作答 <strong>{node.attempt_count || 0}</strong> 次</span>
            </div>
            <div className="map-detail__mastery-evidence">
              {node.status_source === 'combined'
                ? '综合直接作答 + 知识关系权重'
                : '暂无直接作答'}
            </div>
          </div>

          <div className="map-detail__stats-inline">
            <span className="is-correct"><strong>{node.question_stats?.correct || 0}</strong> 答对</span>
            <span className="is-wrong"><strong>{node.question_stats?.wrong || 0}</strong> 答错</span>
            <span className="is-pending"><strong>{node.question_stats?.pending || 0}</strong> 待核验</span>
          </div>

          {node.description ? (
            <p className="map-detail__description">{node.description}</p>
          ) : null}

          <div className="map-detail__meta-group">
            <div className="map-detail__meta-row">
              <span className="map-detail__meta-label">ID</span>
              <span className="map-detail__meta-value">{node.kp_id}</span>
            </div>
            <div className="map-detail__meta-row">
              <span className="map-detail__meta-label">领域</span>
              <span className="map-detail__meta-value">{node.domain || '-'}</span>
            </div>
            <div className="map-detail__meta-row">
              <span className="map-detail__meta-label">分类</span>
              <span className="map-detail__meta-value">{[node.category_1, node.category_2].filter(Boolean).join(' / ') || '-'}</span>
            </div>
            <div className="map-detail__meta-row">
              <span className="map-detail__meta-label">章节</span>
              <span className="map-detail__meta-value">{[node.grade, node.chapter].filter(Boolean).join(' · ') || '-'}</span>
            </div>
            {node.cognitive_level ? (
              <div className="map-detail__meta-row">
                <span className="map-detail__meta-label">能力</span>
                <span className="map-detail__meta-value">{node.cognitive_level}</span>
              </div>
            ) : null}
          </div>

          {(incoming.length > 0 || outgoing.length > 0 || linked.length > 0) ? (
            <div className="map-detail__relations-group">
              <RelationList title="前置知识点" nodes={incoming} />
              <RelationList title="后续知识点" nodes={outgoing} />
          <QuestionHistory
            nodes={linkedAttempts}
            onSelectNode={onSelectNode}
            visibleNodeIds={visibleHistoryIds}
            fixedNodeIds={fixedHistoryIds}
            onToggleNode={onToggleHistoryNode}
          />
            </div>
          ) : null}
        </>
      ) : (
        <>
          <div className="map-detail__q-meta">
            <span>
              {node.view_scope === 'summary'
                ? `全部测试汇总 · ${node.attempt_count || 1} 次作答`
                : TYPE_LABELS[node.question_type || ''] || node.question_type || '-'}
            </span>
            <span className="map-detail__q-score">
              {node.view_scope === 'summary' ? (
                <><strong>{Math.round(questionScorePercent(node))}%</strong> 加权得分率</>
              ) : (
                <><strong>{node.score_got || 0}</strong> / {node.score || 0} 分</>
              )}
            </span>
          </div>

          <div className="map-detail__question">
            {node.content
              ? <ExamQuestionBody content={node.content} options={node.options} paperId={node.source_paper_id} />
              : '暂无题干快照'}
          </div>

          <div className="map-detail__answers">
            <div className={`map-detail__answer-row ${node.status === 'correct' ? 'is-correct' : 'is-wrong'}`}>
              <span className="map-detail__answer-label">你的作答</span>
              <div className="map-detail__answer-value">
                {node.user_answer
                  ? <ExamQuestionBody content={node.user_answer} paperId={node.source_paper_id} />
                  : '-'}
              </div>
            </div>
            <div className="map-detail__answer-row is-correct">
              <span className="map-detail__answer-label">正确答案</span>
              <div className="map-detail__answer-value">
                {node.correct_answer
                  ? <ExamQuestionBody content={node.correct_answer} paperId={node.source_paper_id} />
                  : '-'}
              </div>
            </div>
          </div>

          {node.analysis ? (
            <details className="map-detail__analysis-wrap" open>
              <summary className="map-detail__subtitle">题目解析</summary>
              <div className="map-detail__analysis">
                <ExamQuestionBody content={node.analysis} paperId={node.source_paper_id} />
              </div>
            </details>
          ) : null}

          <RelationList title="考查知识点" nodes={linked} />
        </>
      )}
    </div>
  )
}

function QuestionHistory({
  nodes,
  onSelectNode,
  visibleNodeIds,
  fixedNodeIds,
  onToggleNode,
}: {
  nodes: LearningMapNode[]
  onSelectNode: (nodeId: string) => void
  visibleNodeIds: Set<string>
  fixedNodeIds: Set<string>
  onToggleNode: (nodeId: string, visible: boolean) => void
}) {
  const sorted = [...nodes].sort(
    (a, b) =>
      (b.test_attempt_index || 0) - (a.test_attempt_index || 0) ||
      (a.seq || 0) - (b.seq || 0),
  )
  const identityCounts = sorted.reduce<Record<string, number>>((counts, node) => {
    const key = node.question_identity || node.id
    counts[key] = (counts[key] || 0) + 1
    return counts
  }, {})
  const groups = sorted.reduce<Map<number, LearningMapNode[]>>((result, item) => {
    const key = item.test_paper_id || 0
    result.set(key, [...(result.get(key) || []), item])
    return result
  }, new Map())

  return (
    <div className="map-detail__history">
      <div className="map-detail__subtitle">
        历史作答 <span className="map-detail__history-count">{nodes.length} 条</span>
      </div>
      {nodes.length === 0 ? (
        <div className="map-detail__history-empty">暂无关联题目作答</div>
      ) : (
        [...groups.entries()].map(([paperId, attempts]) => {
          const first = attempts[0]
          return (
            <section className="map-detail__history-group" key={paperId}>
              <header>
                <div>
                  <strong>第 {first.test_attempt_index || '-'} 次测试</strong>
                  <span>{first.test_paper_title || `测试 #${paperId}`}</span>
                </div>
                <time>{formatTestTime(first.tested_at)}</time>
              </header>
              <div className="map-detail__history-list">
                {attempts.map((attempt) => {
                  const repeatedCount =
                    identityCounts[attempt.question_identity || attempt.id] || 1
                  return (
                    <div
                      className={`map-detail__history-item is-${attempt.status}`}
                      key={attempt.id}
                    >
                      <input
                        type="checkbox"
                        checked={visibleNodeIds.has(attempt.id)}
                        disabled={fixedNodeIds.has(attempt.id)}
                        title={
                          fixedNodeIds.has(attempt.id)
                            ? '当前测试题目已默认显示'
                            : '在图谱中附加显示'
                        }
                        aria-label={`在图谱中显示${attempt.label}`}
                        onChange={(event) =>
                          onToggleNode(attempt.id, event.target.checked)
                        }
                      />
                      <button
                        type="button"
                        className="map-detail__history-main"
                        onClick={() => {
                          onToggleNode(attempt.id, true)
                          onSelectNode(attempt.id)
                        }}
                      >
                        <span className="map-detail__history-question">
                          <strong>{attempt.label}</strong>
                          {repeatedCount > 1 && <em>同题共作答 {repeatedCount} 次</em>}
                        </span>
                        <span className="map-detail__history-score">
                          <strong>{attempt.score_got || 0}/{attempt.score || 0}</strong>
                          <em>{Math.round(questionScorePercent(attempt))}%</em>
                        </span>
                      </button>
                    </div>
                  )
                })}
              </div>
            </section>
          )
        })
      )}
    </div>
  )
}

function RelationList({ title, nodes }: { title: string; nodes: LearningMapNode[] }) {
  if (!nodes.length) return null
  return (
    <div className="map-detail__relations">
      <div className="map-detail__subtitle">{title}</div>
      <div>{nodes.map((node) => <Tag key={node.id}>{node.label}</Tag>)}</div>
    </div>
  )
}

export default function LearningMap() {
  const { id, goalId: goalIdParam } = useParams()
  const goalId = Number(goalIdParam || id)
  const navigate = useNavigate()
  const [data, setData] = useState<LearningMapData | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedId, setSelectedId] = useState<string>()
  const [zoom, setZoom] = useState(1)
  const [paperView, setPaperView] = useState<number | 'summary'>('summary')
  const [visibleHistoryIds, setVisibleHistoryIds] = useState<Set<string>>(
    () => new Set(),
  )
  const [filter, setFilter] = useState<'all' | 'knowledge' | 'question'>('all')
  const [filterDomain, setFilterDomain] = useState<string>()
  const [filterCat1, setFilterCat1] = useState<string>()
  const [filterCat2, setFilterCat2] = useState<string>()
  const [panOffset, setPanOffset] = useState<{ x: number; y: number }>({ x: 0, y: 0 })
  const [manualPositions, setManualPositions] = useState<
    Record<string, { x: number; y: number }>
  >({})
  const [draggingId, setDraggingId] = useState<string>()
  const [isPanning, setIsPanning] = useState(false)
  const dragRef = useRef<{
    id: string
    startClientX: number
    startClientY: number
    startX: number
    startY: number
  } | null>(null)
  const panRef = useRef<{
    startClientX: number
    startClientY: number
    startPanX: number
    startPanY: number
  } | null>(null)
  const canvasRef = useRef<HTMLDivElement>(null)
  const initialCenterPendingRef = useRef(true)

  const load = async () => {
    setLoading(true)
    try {
      const response = await goalsApi.learningMap(goalId)
      setData(response.data)
      setPaperView(response.data.paper?.id || 'summary')
      setVisibleHistoryIds(new Set())
      setManualPositions({})
      setPanOffset({ x: 0, y: 0 })
      setZoom(1)
      initialCenterPendingRef.current = true
      const firstKnowledge = response.data.nodes.find((node) => node.node_type === 'knowledge')
      setSelectedId((current) =>
        current && response.data.nodes.some((node) => node.id === current)
          ? current
          : firstKnowledge?.id,
      )
    } catch (error: any) {
      message.error(errorText(error))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (goalId) void load()
  }, [goalId])

  const knowledgeNodes = useMemo(
    () => (data?.nodes || []).filter((n) => n.node_type === 'knowledge'),
    [data],
  )
  const domainOptions = useMemo(() => {
    const set = new Set(knowledgeNodes.map((n) => n.domain).filter(Boolean) as string[])
    return [...set].sort().map((v) => ({ label: v, value: v }))
  }, [knowledgeNodes])
  const cat1Options = useMemo(() => {
    const base = filterDomain
      ? knowledgeNodes.filter((n) => n.domain === filterDomain)
      : knowledgeNodes
    const set = new Set(base.map((n) => n.category_1).filter(Boolean) as string[])
    return [...set].sort().map((v) => ({ label: v, value: v }))
  }, [knowledgeNodes, filterDomain])
  const cat2Options = useMemo(() => {
    let base = filterDomain
      ? knowledgeNodes.filter((n) => n.domain === filterDomain)
      : knowledgeNodes
    if (filterCat1) base = base.filter((n) => n.category_1 === filterCat1)
    const set = new Set(base.map((n) => n.category_2).filter(Boolean) as string[])
    return [...set].sort().map((v) => ({ label: v, value: v }))
  }, [knowledgeNodes, filterDomain, filterCat1])

  const visibleData = useMemo(() => {
    if (!data) return data
    const hasKpFilter = !!(filterDomain || filterCat1 || filterCat2)
    let nodes = data.nodes.filter((node) => {
      if (node.node_type === 'knowledge') return true
      if (paperView === 'summary') return node.view_scope === 'summary'
      return node.view_scope !== 'summary' && node.test_paper_id === paperView
    })
    if (filter !== 'all') {
      nodes = nodes.filter((node) => node.node_type === filter)
    }
    if (hasKpFilter) {
      const matchingKpIds = new Set(
        knowledgeNodes
          .filter((n) => {
            if (filterDomain && n.domain !== filterDomain) return false
            if (filterCat1 && n.category_1 !== filterCat1) return false
            if (filterCat2 && n.category_2 !== filterCat2) return false
            return true
          })
          .map((n) => n.id),
      )
      nodes = nodes.filter((node) => {
        if (node.node_type === 'knowledge') return matchingKpIds.has(node.id)
        // Keep questions linked to matching knowledge points
        return data.edges.some(
          (edge) =>
            edge.type === 'question' &&
            ((edge.source === node.id && matchingKpIds.has(edge.target)) ||
              (edge.target === node.id && matchingKpIds.has(edge.source))),
        )
      })
    }
    const ids = new Set(nodes.map((node) => node.id))
    return { ...data, nodes, edges: data.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)) }
  }, [data, filter, filterDomain, filterCat1, filterCat2, knowledgeNodes, paperView])
  const layout = useMemo(
    () => layoutGraph(visibleData?.nodes || [], visibleData?.edges || []),
    [visibleData],
  )
  const nodeMap = useMemo(
    () => new Map((data?.nodes || []).map((node) => [node.id, node])),
    [data],
  )
  const baseQuestionIds = useMemo(
    () =>
      new Set(
        (visibleData?.nodes || [])
          .filter((node) => node.node_type === 'question')
          .map((node) => node.id),
      ),
    [visibleData],
  )
  const displayedHistoryIds = useMemo(
    () => new Set([...baseQuestionIds, ...visibleHistoryIds]),
    [baseQuestionIds, visibleHistoryIds],
  )
  const supplementalNodes = useMemo(() => {
    if (!data || visibleHistoryIds.size === 0) return [] as PositionedNode[]
    const basePositions = new Map(layout.nodes.map((node) => [node.id, node]))
    const fallbackX = layout.width / 2
    const fallbackY = layout.height / 2
    return [...visibleHistoryIds]
      .filter((nodeId) => !baseQuestionIds.has(nodeId))
      .sort()
      .map((nodeId) => {
        const node = nodeMap.get(nodeId)
        if (!node || node.node_type !== 'question') return null
        const linkedPositions = data.edges
          .filter(
            (edge) =>
              edge.type === 'question' &&
              edge.target === nodeId &&
              basePositions.has(edge.source),
          )
          .map((edge) => basePositions.get(edge.source))
          .filter(Boolean) as PositionedNode[]
        const anchorX = linkedPositions.length
          ? linkedPositions.reduce((sum, item) => sum + item.x, 0) /
            linkedPositions.length
          : fallbackX
        const anchorY = linkedPositions.length
          ? linkedPositions.reduce((sum, item) => sum + item.y, 0) /
            linkedPositions.length
          : fallbackY
        const hash = [...nodeId].reduce(
          (value, char) => (value * 31 + char.charCodeAt(0)) >>> 0,
          2166136261,
        )
        const angle = ((hash % 360) * Math.PI) / 180
        const radius = 105 + (hash % 4) * 18
        return {
          ...node,
          x: Math.min(
            layout.width - 48,
            Math.max(48, anchorX + Math.cos(angle) * radius),
          ),
          y: Math.min(
            layout.height - 36,
            Math.max(36, anchorY + Math.sin(angle) * radius * 0.76),
          ),
        }
      })
      .filter(Boolean) as PositionedNode[]
  }, [
    baseQuestionIds,
    data,
    layout.height,
    layout.nodes,
    layout.width,
    nodeMap,
    visibleHistoryIds,
  ])
  const displayNodes = useMemo(
    () =>
      [...layout.nodes, ...supplementalNodes].map((node) => ({
        ...node,
        ...(manualPositions[node.id] || {}),
      })),
    [layout.nodes, manualPositions, supplementalNodes],
  )
  const positionMap = useMemo(
    () => new Map(displayNodes.map((node) => [node.id, node])),
    [displayNodes],
  )
  const displayEdges = useMemo(() => {
    if (!data || !visibleData) return [] as LearningMapEdge[]
    const baseIds = new Set(visibleData.nodes.map((node) => node.id))
    const supplementalIds = new Set(supplementalNodes.map((node) => node.id))
    const combined = [
      ...visibleData.edges,
      ...data.edges.filter(
        (edge) =>
          edge.type === 'question' &&
          supplementalIds.has(edge.target) &&
          baseIds.has(edge.source),
      ),
    ]
    return [...new Map(combined.map((edge) => [edge.id, edge])).values()]
  }, [data, supplementalNodes, visibleData])
  const canvasSize = useMemo(
    () => ({
      width: Math.max(layout.width, ...displayNodes.map((node) => node.x + 100)),
      height: Math.max(layout.height, ...displayNodes.map((node) => node.y + 90)),
    }),
    [displayNodes, layout.height, layout.width],
  )
  const selected = selectedId ? nodeMap.get(selectedId) || null : null

  useEffect(() => {
    setManualPositions({})
    setPanOffset({ x: 0, y: 0 })
    initialCenterPendingRef.current = true
    if (
      selectedId &&
      !visibleData?.nodes.some((node) => node.id === selectedId)
    ) {
      const firstKnowledge = visibleData?.nodes.find(
        (node) => node.node_type === 'knowledge',
      )
      setSelectedId(firstKnowledge?.id)
    }
  }, [paperView])

  useEffect(() => {
    if (
      !data ||
      !initialCenterPendingRef.current ||
      displayNodes.length === 0
    ) {
      return
    }
    const frame = window.requestAnimationFrame(() => {
      const canvas = canvasRef.current
      if (!canvas) return
      const minX = Math.min(...displayNodes.map((node) => node.x - 56))
      const maxX = Math.max(...displayNodes.map((node) => node.x + 56))
      const minY = Math.min(...displayNodes.map((node) => node.y - 42))
      const maxY = Math.max(...displayNodes.map((node) => node.y + 42))
      const graphWidth = Math.max(1, maxX - minX)
      const graphHeight = Math.max(1, maxY - minY)
      const fitZoom = Math.min(
        1,
        Math.max(
          0.6,
          Math.min(
            (canvas.clientWidth - 72) / graphWidth,
            (canvas.clientHeight - 72) / graphHeight,
          ),
        ),
      )
      const graphCenterX = (minX + maxX) / 2
      const graphCenterY = (minY + maxY) / 2
      setZoom(fitZoom)
      setPanOffset({
        x: canvas.clientWidth / 2 - graphCenterX * fitZoom,
        y: canvas.clientHeight / 2 - graphCenterY * fitZoom,
      })
      initialCenterPendingRef.current = false
    })
    return () => window.cancelAnimationFrame(frame)
  }, [data, displayNodes])

  const startDrag = (event: React.PointerEvent<SVGGElement>, node: PositionedNode) => {
    event.preventDefault()
    event.stopPropagation()
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = {
      id: node.id,
      startClientX: event.clientX,
      startClientY: event.clientY,
      startX: node.x,
      startY: node.y,
    }
    setDraggingId(node.id)
    setSelectedId(node.id)
  }

  const moveDrag = (event: React.PointerEvent<SVGGElement>) => {
    const drag = dragRef.current
    if (!drag) return
    const x = Math.max(48, drag.startX + (event.clientX - drag.startClientX) / zoom)
    const y = Math.max(42, drag.startY + (event.clientY - drag.startClientY) / zoom)
    setManualPositions((current) => ({ ...current, [drag.id]: { x, y } }))
  }

  const endDrag = (event: React.PointerEvent<SVGGElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    dragRef.current = null
    setDraggingId(undefined)
  }

  const startPan = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    // Only pan on left-click directly on the canvas/svg background
    if (event.button !== 0) return
    const target = event.target as HTMLElement
    const tag = target.tagName.toLowerCase()
    // Allow pan only when clicking on the canvas div, svg root, or svg defs/path (edges)
    if (tag !== 'div' && tag !== 'svg' && tag !== 'path' && tag !== 'defs') return
    event.preventDefault()
    ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
    panRef.current = {
      startClientX: event.clientX,
      startClientY: event.clientY,
      startPanX: panOffset.x,
      startPanY: panOffset.y,
    }
    setIsPanning(true)
  }, [panOffset])

  const movePan = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    const pan = panRef.current
    if (!pan) return
    setPanOffset({
      x: pan.startPanX + (event.clientX - pan.startClientX),
      y: pan.startPanY + (event.clientY - pan.startClientY),
    })
  }, [])

  const endPan = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if ((event.currentTarget as HTMLElement).hasPointerCapture(event.pointerId)) {
      ;(event.currentTarget as HTMLElement).releasePointerCapture(event.pointerId)
    }
    panRef.current = null
    setIsPanning(false)
  }, [])

  const handleWheel = useCallback((event: React.WheelEvent<HTMLDivElement>) => {
    event.preventDefault()
    const delta = event.deltaY > 0 ? -0.05 : 0.05
    setZoom((value) => Math.min(1.5, Math.max(0.6, value + delta)))
  }, [])

  if (loading) {
    return <div className="learning-map-loading"><Spin tip="正在生成学习地图…" /></div>
  }
  if (!data) return <Alert type="error" message="学习地图加载失败" showIcon />

  return (
    <div className="learning-map-page">
      <div className="learning-map-header">
        <div>
          <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate('/goals')}>
            返回学习目标
          </Button>
          <Typography.Title level={3}>{data.goal.title} · 学习地图</Typography.Title>
          <Typography.Text type="secondary">
            {data.goal.grade_stage} · {data.summary.knowledge_count} 个知识点 · {data.summary.relation_count} 条关系
          </Typography.Text>
        </div>
        <Space>
          <Button icon={<CompassOutlined />} onClick={() => navigate(`/goals/${goalId}/path`)}>
            生成学习路径
          </Button>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新地图</Button>
        </Space>
      </div>

      {!data.summary.has_assessment && (
        <Alert
          type="info"
          showIcon
          message="当前目标还没有已批改测评，地图暂只展示知识点关系"
          style={{ marginBottom: 14 }}
        />
      )}

      <div className="learning-map-layout">
        <section className="learning-map-graph">
          <div className="learning-map-toolbar">
            <Segmented
              value={filter}
              onChange={(value) => setFilter(value as typeof filter)}
              options={[
                { label: '全部', value: 'all' },
                { label: '知识点', value: 'knowledge' },
                { label: '题目', value: 'question' },
              ]}
            />
            <div className="learning-map-filters">
              <Select
                className="learning-map-paper-select"
                value={paperView}
                onChange={(value) => {
                  setPaperView(value as number | 'summary')
                  setVisibleHistoryIds(new Set())
                }}
                options={[
                  {
                    label: `全部测试汇总（${data.papers?.length || 0} 次）`,
                    value: 'summary',
                  },
                  ...(data.papers || []).map((paper) => ({
                    label: `第 ${paper.attempt_index} 次 · ${paper.title} · ${
                      paper.earned_score ?? '-'
                    }/${paper.total_score ?? '-'}`,
                    value: paper.id,
                  })),
                ]}
              />
              <Select
                className="learning-map-filter-select"
                placeholder="知识领域"
                allowClear
                value={filterDomain}
                options={domainOptions}
                onChange={(value) => {
                  setFilterDomain(value)
                  setFilterCat1(undefined)
                  setFilterCat2(undefined)
                }}
              />
              <Select
                className="learning-map-filter-select"
                placeholder="一级分类"
                allowClear
                value={filterCat1}
                options={cat1Options}
                onChange={(value) => {
                  setFilterCat1(value)
                  setFilterCat2(undefined)
                }}
              />
              <Select
                className="learning-map-filter-select"
                placeholder="二级分类"
                allowClear
                value={filterCat2}
                options={cat2Options}
                onChange={setFilterCat2}
              />
            </div>
            <div className="learning-map-controls">
              <Tooltip title="恢复系统生成的星型布局">
                <Button
                  className="learning-map-reset"
                  size="small"
                  icon={<UndoOutlined />}
                  disabled={Object.keys(manualPositions).length === 0 && panOffset.x === 0 && panOffset.y === 0}
                  onClick={() => { setManualPositions({}); setPanOffset({ x: 0, y: 0 }) }}
                >
                  重置布局
                </Button>
              </Tooltip>
              <div className="learning-map-zoom" aria-label="图谱缩放">
                <Tooltip title="缩小">
                  <Button
                    type="text"
                    size="small"
                    icon={<MinusOutlined />}
                    disabled={zoom <= 0.6}
                    onClick={() => setZoom((value) => Math.max(.6, value - .1))}
                  />
                </Tooltip>
                <button
                  type="button"
                  className="learning-map-zoom__value"
                  title="恢复为 100%"
                  onClick={() => setZoom(1)}
                >
                  {Math.round(zoom * 100)}%
                </button>
                <Tooltip title="放大">
                  <Button
                    type="text"
                    size="small"
                    icon={<PlusOutlined />}
                    disabled={zoom >= 1.5}
                    onClick={() => setZoom((value) => Math.min(1.5, value + .1))}
                  />
                </Tooltip>
              </div>
            </div>
          </div>
          <div className="learning-map-legend">
            <div className="legend-scale" aria-label="掌握度色阶">
              <span className="legend-scale__end is-weak">需加强</span>
              <div className="legend-scale__bar" />
              <span className="legend-scale__end is-strong">已掌握</span>
            </div>
            <div className="legend-items">
              <span><i className="legend-dot mastery-l1" />0～20</span>
              <span><i className="legend-dot mastery-l2" />21～40</span>
              <span><i className="legend-dot mastery-l3" />41～59</span>
              <span><i className="legend-dot mastery-l4" />60～74</span>
              <span><i className="legend-dot mastery-l5" />75～89</span>
              <span><i className="legend-dot mastery-l6" />90～100</span>
              <span><i className="legend-dot mastery-l0" />未测评</span>
              <span className="legend-question-score" aria-label="题目得分率：0%为红色，100%为绿色">
                <span className="legend-question-score__title">题目得分率</span>
                <span className="legend-question-score__value is-low">0%</span>
                <i className="legend-question is-score" aria-hidden="true" />
                <span className="legend-question-score__value is-high">100%</span>
                <span className="legend-question-score__formula">（得分÷满分）</span>
              </span>
            </div>
            <span className="learning-map-drag-hint">拖拽画布 / 节点 · 滚轮缩放</span>
          </div>
          <div
            ref={canvasRef}
            className={`learning-map-canvas${isPanning ? ' is-panning' : ''}`}
            onPointerDown={startPan}
            onPointerMove={movePan}
            onPointerUp={endPan}
            onPointerCancel={endPan}
            onWheel={handleWheel}
          >
            {layout.nodes.length === 0 ? (
              <Empty description="当前筛选下暂无节点" />
            ) : (
              <svg
                width={canvasSize.width}
                height={canvasSize.height}
                viewBox={`0 0 ${canvasSize.width} ${canvasSize.height}`}
                aria-label="学习知识图谱"
              >
                <defs>
                  <marker id="map-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
                    <path d="M0,0 L7,3.5 L0,7 Z" fill="#9aafad" />
                  </marker>
                  <filter id="node-flat-shadow" x="-35%" y="-30%" width="170%" height="180%">
                    <feDropShadow dx="0" dy="1.5" stdDeviation="1.8" floodColor="#14363a" floodOpacity="0.12" />
                  </filter>
                </defs>
                <g transform={`translate(${panOffset.x} ${panOffset.y}) scale(${zoom})`}>
                <g className="map-edges">
                  {displayEdges.map((edge) => {
                    const source = positionMap.get(edge.source)
                    const target = positionMap.get(edge.target)
                    if (!source || !target) return null
                    const middleX =
                      source.x === target.x
                        ? source.x + 54
                        : source.x + (target.x - source.x) * 0.5
                    return (
                      <path
                        key={edge.id}
                        d={`M ${source.x} ${source.y} C ${middleX} ${source.y}, ${middleX} ${target.y}, ${target.x} ${target.y}`}
                        className={`map-edge map-edge--${edge.type}`}
                        markerEnd="url(#map-arrow)"
                      />
                    )
                  })}
                </g>
                {displayNodes.map((node) => (
                  <g
                    key={node.id}
                    className={`${nodeClass(node, node.id === selectedId)}${
                      node.id === draggingId ? ' is-dragging' : ''
                    }`}
                    transform={`translate(${node.x} ${node.y})`}
                    role="button"
                    tabIndex={0}
                    onClick={() => setSelectedId(node.id)}
                    onPointerDown={(event) => startDrag(event, node)}
                    onPointerMove={moveDrag}
                    onPointerUp={endDrag}
                    onPointerCancel={endDrag}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') setSelectedId(node.id)
                    }}
                  >
                    <g className="map-node__content">
                    {node.id === selectedId && (
                      node.node_type === 'knowledge' ? (
                        <circle r="33" className="map-node__selection-pulse" />
                      ) : (
                        <rect
                          x="-39"
                          y="-19"
                          width="78"
                          height="38"
                          rx="10"
                          className="map-node__selection-pulse"
                        />
                      )
                    )}
                    {node.node_type === 'knowledge' ? (
                      <circle r="28" className="map-node__body" />
                    ) : (
                      <rect x="-34" y="-14" width="68" height="28" rx="7" className="map-node__body" />
                    )}
                    <MapNodeText node={node} />
                    </g>
                  </g>
                ))}
                </g>
              </svg>
            )}
          </div>
        </section>

        <aside className="learning-map-detail">
          <DetailPanel
            node={selected}
            nodeMap={nodeMap}
            edges={data.edges}
            onSelectNode={setSelectedId}
            visibleHistoryIds={displayedHistoryIds}
            fixedHistoryIds={baseQuestionIds}
            onToggleHistoryNode={(nodeId, visible) => {
              setVisibleHistoryIds((current) => {
                const next = new Set(current)
                if (visible) next.add(nodeId)
                else next.delete(nodeId)
                return next
              })
              if (!visible && selectedId === nodeId) {
                const linkedKnowledgeId = data.edges.find(
                  (edge) => edge.type === 'question' && edge.target === nodeId,
                )?.source
                setSelectedId(linkedKnowledgeId)
              }
            }}
          />
        </aside>
      </div>
    </div>
  )
}

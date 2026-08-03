import ReactMarkdown from 'react-markdown'
import './explanation-blocks.css'

export interface ExplanationContentBlock {
  type: 'markdown' | 'visual'
  content?: string
  visual_type?: 'geometry' | 'number_line' | 'coordinate_plane' | 'function_plot' | 'bar_chart' | 'line_chart'
  title?: string
  caption?: string
  alt?: string
  spec?: Record<string, any>
}

const PALETTE: Record<string, string> = {
  teal: '#16877c',
  blue: '#3978c5',
  orange: '#e58a35',
  red: '#d95757',
  green: '#3a9a68',
  purple: '#8267b3',
  gray: '#708889',
}

const color = (value: unknown, fallback = 'teal') => PALETTE[String(value)] || PALETTE[fallback]
const number = (value: unknown, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback
const list = <T,>(value: unknown): T[] => Array.isArray(value) ? value : []

function GeometryVisual({ spec }: { spec: Record<string, any> }) {
  const points = list<any>(spec.points)
  const byId = new Map(points.map((point) => [String(point.id), point]))
  const pointList = (ids: unknown) => list<string>(ids).map((id) => byId.get(String(id))).filter(Boolean)
  return (
    <svg viewBox="0 0 100 100" role="img" aria-hidden="true">
      {list<any>(spec.polygons).map((polygon, index) => {
        const vertices = pointList(polygon.points)
        if (vertices.length < 3) return null
        return (
          <polygon
            key={`polygon-${index}`}
            points={vertices.map((point) => `${number(point.x)},${number(point.y)}`).join(' ')}
            fill={color(polygon.color)}
            fillOpacity=".1"
            stroke={color(polygon.color)}
            strokeWidth="1"
            strokeLinejoin="round"
          />
        )
      })}
      {list<any>(spec.circles).map((circle, index) => {
        const center = byId.get(String(circle.center))
        if (!center) return null
        return (
          <circle
            key={`circle-${index}`}
            cx={number(center.x)}
            cy={number(center.y)}
            r={number(circle.radius, 15)}
            fill={color(circle.color)}
            fillOpacity=".06"
            stroke={color(circle.color)}
            strokeWidth="1"
          />
        )
      })}
      {list<any>(spec.segments).map((segment, index) => {
        const start = byId.get(String(segment.from))
        const end = byId.get(String(segment.to))
        if (!start || !end) return null
        const midX = (number(start.x) + number(end.x)) / 2
        const midY = (number(start.y) + number(end.y)) / 2
        return (
          <g key={`segment-${index}`}>
            <line
              x1={number(start.x)}
              y1={number(start.y)}
              x2={number(end.x)}
              y2={number(end.y)}
              stroke={color(segment.color, 'gray')}
              strokeWidth="1.2"
              strokeDasharray={segment.dashed ? '3 2' : undefined}
              strokeLinecap="round"
            />
            {segment.label && <text x={midX} y={midY - 2} textAnchor="middle">{segment.label}</text>}
          </g>
        )
      })}
      {points.map((point, index) => (
        <g key={`point-${point.id || index}`}>
          <circle cx={number(point.x)} cy={number(point.y)} r="1.7" fill={color(point.color)} />
          {(point.label || point.id) && (
            <text x={number(point.x) + 2.3} y={number(point.y) - 2.3}>{point.label || point.id}</text>
          )}
        </g>
      ))}
    </svg>
  )
}

function NumberLineVisual({ spec }: { spec: Record<string, any> }) {
  const min = number(spec.min, -5)
  const max = number(spec.max, 5)
  const step = Math.max(number(spec.step, 1), 0.1)
  const toX = (value: number) => 8 + ((value - min) / Math.max(max - min, 1)) * 84
  const ticks: number[] = []
  for (let value = min, count = 0; value <= max + step / 100 && count < 21; value += step, count += 1) {
    ticks.push(Number(value.toFixed(4)))
  }
  return (
    <svg viewBox="0 0 100 32" role="img" aria-hidden="true">
      <line x1="6" y1="16" x2="94" y2="16" stroke={PALETTE.gray} strokeWidth=".8" />
      <path d="M94 16 L91 14 L91 18 Z" fill={PALETTE.gray} />
      {list<any>(spec.ranges).map((range, index) => (
        <g key={`range-${index}`}>
          <line
            x1={toX(number(range.from))}
            y1="11"
            x2={toX(number(range.to))}
            y2="11"
            stroke={color(range.color, 'blue')}
            strokeWidth="2.2"
            strokeLinecap="round"
          />
          {range.label && <text x={(toX(number(range.from)) + toX(number(range.to))) / 2} y="7" textAnchor="middle">{range.label}</text>}
        </g>
      ))}
      {ticks.map((tick) => (
        <g key={tick}>
          <line x1={toX(tick)} y1="13.5" x2={toX(tick)} y2="18.5" stroke={PALETTE.gray} strokeWidth=".55" />
          <text x={toX(tick)} y="24" textAnchor="middle">{tick}</text>
        </g>
      ))}
      {list<any>(spec.markers).map((marker, index) => (
        <g key={`marker-${index}`}>
          <circle cx={toX(number(marker.value))} cy="16" r="2.2" fill="#fff" stroke={color(marker.color)} strokeWidth="1.2" />
          <text x={toX(number(marker.value))} y="30" textAnchor="middle" fill={color(marker.color)}>
            {marker.label || marker.value}
          </text>
        </g>
      ))}
    </svg>
  )
}

function CoordinateVisual({ spec }: { spec: Record<string, any> }) {
  const xMin = number(spec.x_min, -5)
  const xMax = number(spec.x_max, 5)
  const yMin = number(spec.y_min, -5)
  const yMax = number(spec.y_max, 5)
  const toX = (value: number) => 9 + ((value - xMin) / Math.max(xMax - xMin, 1)) * 82
  const toY = (value: number) => 68 - ((value - yMin) / Math.max(yMax - yMin, 1)) * 58
  const xAxis = Math.max(10, Math.min(68, toY(0)))
  const yAxis = Math.max(9, Math.min(91, toX(0)))
  const grid = Array.from({ length: 11 }, (_, index) => index)
  return (
    <svg viewBox="0 0 100 76" role="img" aria-hidden="true">
      {spec.grid !== false && grid.map((index) => (
        <g key={index}>
          <line x1={9 + index * 8.2} y1="10" x2={9 + index * 8.2} y2="68" stroke="#dfeae9" strokeWidth=".35" />
          <line x1="9" y1={10 + index * 5.8} x2="91" y2={10 + index * 5.8} stroke="#dfeae9" strokeWidth=".35" />
        </g>
      ))}
      <line x1="7" y1={xAxis} x2="94" y2={xAxis} stroke={PALETTE.gray} strokeWidth=".65" />
      <line x1={yAxis} y1="71" x2={yAxis} y2="7" stroke={PALETTE.gray} strokeWidth=".65" />
      <path d={`M94 ${xAxis} L91 ${xAxis - 1.8} L91 ${xAxis + 1.8} Z`} fill={PALETTE.gray} />
      <path d={`M${yAxis} 7 L${yAxis - 1.8} 10 L${yAxis + 1.8} 10 Z`} fill={PALETTE.gray} />
      <text x="94" y={xAxis - 2.5} textAnchor="end">{spec.x_label || 'x'}</text>
      <text x={yAxis + 2.4} y="8">{spec.y_label || 'y'}</text>
      {list<any>(spec.series).map((series, index) => {
        const points = list<any>(series.points)
        return (
          <g key={`series-${index}`}>
            <polyline
              points={points.map((point) => `${toX(number(point.x))},${toY(number(point.y))}`).join(' ')}
              fill="none"
              stroke={color(series.color)}
              strokeWidth="1.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            {series.label && points[points.length - 1] && (
              <text
                x={toX(number(points[points.length - 1].x)) - 1}
                y={toY(number(points[points.length - 1].y)) - 2}
                textAnchor="end"
                fill={color(series.color)}
              >
                {series.label}
              </text>
            )}
          </g>
        )
      })}
      {list<any>(spec.points).map((point, index) => (
        <g key={`coordinate-point-${index}`}>
          <circle cx={toX(number(point.x))} cy={toY(number(point.y))} r="1.7" fill={color(point.color, 'red')} />
          {point.label && <text x={toX(number(point.x)) + 2.2} y={toY(number(point.y)) - 2}>{point.label}</text>}
        </g>
      ))}
    </svg>
  )
}

function ChartVisual({ spec, line }: { spec: Record<string, any>; line: boolean }) {
  const labels = list<string>(spec.labels)
  const series = list<any>(spec.series)
  const values = series.flatMap((item) => list<number>(item.values).map((value) => number(value)))
  const min = Math.min(0, ...values)
  const max = Math.max(1, ...values)
  const toY = (value: number) => 62 - ((value - min) / Math.max(max - min, 1)) * 50
  const zeroY = toY(0)
  const slot = 82 / Math.max(labels.length, 1)
  return (
    <svg viewBox="0 0 100 72" role="img" aria-hidden="true">
      {Array.from({ length: 6 }, (_, index) => (
        <line key={index} x1="10" y1={12 + index * 10} x2="94" y2={12 + index * 10} stroke="#e4edec" strokeWidth=".35" />
      ))}
      <line x1="10" y1={zeroY} x2="94" y2={zeroY} stroke={PALETTE.gray} strokeWidth=".65" />
      {line ? series.map((item, seriesIndex) => (
        <polyline
          key={seriesIndex}
          points={list<number>(item.values).map((value, index) => `${14 + index * slot + slot / 2},${toY(number(value))}`).join(' ')}
          fill="none"
          stroke={color(item.color)}
          strokeWidth="1.3"
          strokeLinejoin="round"
        />
      )) : series.flatMap((item, seriesIndex) => (
        list<number>(item.values).map((value, index) => {
          const width = Math.max(1.5, slot * .68 / Math.max(series.length, 1))
          const x = 14 + index * slot + seriesIndex * width
          const y = toY(number(value))
          return (
            <rect
              key={`${seriesIndex}-${index}`}
              x={x}
              y={Math.min(y, zeroY)}
              width={width - .5}
              height={Math.max(1, Math.abs(zeroY - y))}
              rx=".8"
              fill={color(item.color)}
              fillOpacity=".78"
            />
          )
        })
      ))}
      {labels.map((label, index) => (
        <text key={label + index} x={14 + index * slot + slot / 2} y="69" textAnchor="middle">{label}</text>
      ))}
      {spec.y_label && <text x="10" y="8">{spec.y_label}</text>}
    </svg>
  )
}

function MathVisual({ block }: { block: ExplanationContentBlock }) {
  const spec = block.spec || {}
  switch (block.visual_type) {
    case 'geometry':
      return <GeometryVisual spec={spec} />
    case 'number_line':
      return <NumberLineVisual spec={spec} />
    case 'coordinate_plane':
    case 'function_plot':
      return <CoordinateVisual spec={spec} />
    case 'bar_chart':
      return <ChartVisual spec={spec} line={false} />
    case 'line_chart':
      return <ChartVisual spec={spec} line />
    default:
      return null
  }
}

export function ExplanationBlocks({
  blocks,
  fallbackContent,
}: {
  blocks?: ExplanationContentBlock[]
  fallbackContent: string
}) {
  const contentBlocks = blocks?.length
    ? blocks
    : fallbackContent
      ? [{ type: 'markdown' as const, content: fallbackContent }]
      : []
  return (
    <div className="explanation-blocks">
      {contentBlocks.map((block, index) => {
        if (block.type === 'markdown') {
          return <div className="explanation-markdown" key={`markdown-${index}`}><ReactMarkdown>{block.content || ''}</ReactMarkdown></div>
        }
        return (
          <figure className="explanation-visual" key={`visual-${index}`} aria-label={block.alt || block.caption || block.title}>
            {block.title && <div className="explanation-visual-title">{block.title}</div>}
            <div className="explanation-visual-canvas"><MathVisual block={block} /></div>
            {block.caption && <figcaption>{block.caption}</figcaption>}
          </figure>
        )
      })}
    </div>
  )
}

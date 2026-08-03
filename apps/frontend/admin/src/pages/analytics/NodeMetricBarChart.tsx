export type NodeMetricBarRow = {
  label: string
  value: number | null
  unit: string
  comparisonValue?: number | null
  note?: string
}

export type NodeMetricBarGroup = {
  title: string
  description: string
  primaryLabel: string
  comparisonLabel?: string
  rows: NodeMetricBarRow[]
}

function formatValue(value: number | null | undefined, unit: string) {
  if (value == null) return '暂无'
  const digits = Number.isInteger(value) ? 0 : Math.abs(value) >= 10 ? 1 : 3
  return `${value.toFixed(digits)}${unit}`
}

export default function NodeMetricBarChart({ group }: { group: NodeMetricBarGroup }) {
  const values = group.rows.flatMap(row => [
    typeof row.value === 'number' ? row.value : 0,
    typeof row.comparisonValue === 'number' ? row.comparisonValue : 0,
  ])
  const usesPercent = group.rows.every(row => row.unit === '%')
  const maximum = usesPercent ? 100 : Math.max(...values, 1)
  const widthOf = (value: number | null | undefined) =>
    `${Math.max(0, Math.min(100, ((value ?? 0) / maximum) * 100))}%`

  return (
    <section className="node-metric-chart">
      <header>
        <div>
          <h3>{group.title}</h3>
          <p>{group.description}</p>
        </div>
        <div className="node-metric-chart-legend">
          <span><i className="node-metric-legend-primary" />{group.primaryLabel}</span>
          {group.comparisonLabel && (
            <span><i className="node-metric-legend-secondary" />{group.comparisonLabel}</span>
          )}
        </div>
      </header>
      <div className="node-metric-chart-body">
        {group.rows.map(row => (
          <div className="node-metric-chart-row" key={`${group.title}-${row.label}`}>
            <strong title={row.label}>{row.label}</strong>
            <div className="node-metric-bars">
              <div className="node-metric-bar-line">
                <span style={{ width: widthOf(row.value) }} />
                <em>{formatValue(row.value, row.unit)}</em>
              </div>
              {group.comparisonLabel && (
                <div className="node-metric-bar-line node-metric-bar-secondary">
                  <span style={{ width: widthOf(row.comparisonValue) }} />
                  <em>{formatValue(row.comparisonValue, row.unit)}</em>
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

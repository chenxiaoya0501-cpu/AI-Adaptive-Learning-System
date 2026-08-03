import { FilterOutlined } from '@ant-design/icons'
import { Select, Skeleton } from 'antd'
import type { KnowledgeDirectoryOptions, KnowledgeScopeParams } from '../../api'

type Props = {
  options: KnowledgeDirectoryOptions | null
  value: KnowledgeScopeParams
  loading?: boolean
  selectedCount?: number
  onChange: (value: KnowledgeScopeParams) => void
}

export default function KnowledgeScopeSelector({
  options,
  value,
  loading,
  selectedCount,
  onChange,
}: Props) {
  if (loading && !options) {
    return <Skeleton.Input active block className="knowledge-filter-skeleton" />
  }

  const categories1 = (options?.categories_1 ?? []).filter(
    item => item.domain === value.domain,
  )
  const categories2 = (options?.categories_2 ?? []).filter(
    item => item.domain === value.domain && item.category_1 === value.category_1,
  )
  const knowledgePoints = (options?.knowledge_points ?? []).filter(
    item =>
      item.domain === value.domain &&
      item.category_1 === value.category_1 &&
      item.category_2 === value.category_2,
  )

  return (
    <section className="knowledge-scope-filter">
      <div className="knowledge-filter-title">
        <FilterOutlined />
        <div>
          <strong>知识点统计范围</strong>
          <span>不选择时统计全部知识点；选择目录后统计其包含知识点的平均指标</span>
        </div>
      </div>
      <div className="knowledge-filter-controls">
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="全部知识领域"
          value={value.domain}
          options={options?.domains ?? []}
          onChange={domain => onChange(domain ? { domain } : {})}
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="全部一级目录"
          disabled={!value.domain}
          value={value.category_1}
          options={categories1}
          onChange={category_1 =>
            onChange(category_1 ? { domain: value.domain, category_1 } : { domain: value.domain })
          }
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="全部二级目录"
          disabled={!value.category_1}
          value={value.category_2}
          options={categories2}
          onChange={category_2 =>
            onChange(
              category_2
                ? { domain: value.domain, category_1: value.category_1, category_2 }
                : { domain: value.domain, category_1: value.category_1 },
            )
          }
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="全部知识点"
          disabled={!value.category_2}
          value={value.kp_id}
          options={knowledgePoints}
          onChange={kp_id =>
            onChange(
              kp_id
                ? { ...value, kp_id }
                : {
                    domain: value.domain,
                    category_1: value.category_1,
                    category_2: value.category_2,
                  },
            )
          }
        />
      </div>
      <div className="knowledge-filter-result">
        当前范围：
        <strong>
          {value.kp_id
            ? knowledgePoints.find(item => item.value === value.kp_id)?.label
            : value.category_2 || value.category_1 || value.domain || '全部知识点'}
        </strong>
        {typeof selectedCount === 'number' && (
          <span>，包含 {selectedCount} 个知识点</span>
        )}
      </div>
    </section>
  )
}

import { useMemo } from 'react'
import { Empty, Tree, Typography } from 'antd'
import type { DataNode } from 'antd/es/tree'
import type { ChapterNode, ChapterTree } from '../../api/assets'

type Props = {
  trees: ChapterTree[]
  value: number[]
  onChange: (ids: number[]) => void
  /** 根节点展示名，如「九年级下」 */
  rootLabel?: string
}

/** 只取章级节点，不展示节 */
function getChaptersOnly(nodes: ChapterNode[]): ChapterNode[] {
  return nodes.filter((n) => n.level !== 'section')
}

function toChapterLeafData(chapters: ChapterNode[]): DataNode[] {
  return chapters.map((n) => {
    const kpHint =
      n.kp_count && n.kp_count > 0 ? `（约 ${n.kp_count} 个知识点）` : '（暂无知识点）'
    return {
      key: String(n.id),
      title: (
        <span>
          {n.title}
          <Typography.Text type="secondary" style={{ marginLeft: 6, fontSize: 12 }}>
            {kpHint}
          </Typography.Text>
        </span>
      ),
      isLeaf: true,
    }
  })
}

function fallbackLabel(trees: ChapterTree[]): string {
  const t = trees[0]
  if (!t) return '章节目录'
  const g = t.grade || ''
  const s = t.semester || ''
  const gradeMap: Record<string, string> = { '7': '七年级', '8': '八年级', '9': '九年级' }
  const gradeName = gradeMap[String(g)] || g
  if (gradeName && s) return `${gradeName}${s}`
  return gradeName || '章节目录'
}

export default function ChapterPicker({ trees, value, onChange, rootLabel }: Props) {
  const label = rootLabel || fallbackLabel(trees)

  const chapters = useMemo(
    () => trees.flatMap((t) => getChaptersOnly(t.nodes)),
    [trees],
  )

  const treeData = useMemo(
    () => [
      {
        key: 'grade-root',
        title: label,
        // 可勾选：选中表示该年级下全部章全选 / 取消全选
        children: toChapterLeafData(chapters),
      },
    ],
    [chapters, label],
  )

  const chapterIdSet = useMemo(() => new Set(chapters.map((c) => c.id)), [chapters])

  const checkedKeys = useMemo(
    () => value.filter((id) => chapterIdSet.has(id)).map(String),
    [value, chapterIdSet],
  )

  if (!trees.length) {
    return <Empty description="当前年级阶段暂无章节目录，请先在管理端完成对应教材抽取" />
  }

  if (!chapters.length) {
    return <Empty description="当前年级阶段暂无章目录" />
  }

  return (
    <Tree
      key={label}
      checkable
      defaultExpandedKeys={['grade-root']}
      checkedKeys={checkedKeys}
      treeData={treeData}
      onCheck={(checked) => {
        const keys = Array.isArray(checked) ? checked : checked.checked
        const ids = keys
          .map(String)
          .filter((k) => k !== 'grade-root')
          .map((k) => Number(k))
          .filter((n) => !Number.isNaN(n) && chapterIdSet.has(n))
        onChange(ids)
      }}
      style={{ background: '#fff', padding: 8, borderRadius: 8, maxHeight: 420, overflow: 'auto' }}
    />
  )
}

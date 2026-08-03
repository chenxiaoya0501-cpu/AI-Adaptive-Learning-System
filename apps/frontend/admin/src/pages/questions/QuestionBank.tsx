import React, { useEffect, useState } from 'react'
import {
  Table, Button, Space, Tag, Modal, Form, Input, Select, InputNumber,
  message, Popconfirm, Card, Typography, Upload, Tooltip, Drawer, Progress, Radio, Dropdown
} from 'antd'
import {
  DeleteOutlined, EditOutlined, UploadOutlined,
  ReloadOutlined, FileWordOutlined, EyeOutlined, ThunderboltOutlined,
  ProfileOutlined, UnorderedListOutlined, FontSizeOutlined, DownOutlined
} from '@ant-design/icons'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import { questionApi, knowledgeApi } from '../../api'
import AnswerFormulaInput from '../../components/AnswerFormulaInput'

const { Title, Text } = Typography
const { Option } = Select
const { TextArea } = Input

// 解析 [IMG:filename,W,H] 或 [IMG:filename] 格式
function parseImgPlaceholder(placeholder: string) {
  const m = placeholder.match(/\[IMG:([^,\]]+)(?:,([\d.]+),([\d.]+))?\]/)
  if (!m) return null
  return { filename: m[1], wPt: m[2] ? parseFloat(m[2]) : 0, hPt: m[3] ? parseFloat(m[3]) : 0 }
}

/**
 * 答案展示排版：对齐「图片答案」多行格式
 * - (1)(2) 小题换行，题号后双空格
 * - 变量两侧空格：C=5 → C = 5
 * - 分式两侧「或」留空
 */
function formatAnswerLayout(text: string): string {
  if (!text) return text
  return text.split(/(\[IMG:[^\]]+\])/g).map((part) => {
    if (part.startsWith('[IMG:')) return part
    let s = part.replace(/\r\n/g, '\n')
    // 全角小题号 → 半角（避开坐标 (2,1)）
    s = s.replace(/（(\d{1,2})）(?![,，.]\d)/g, '($1)')
    // 粘连的 (2)(3)… 小题前换行（(2,1) 不会匹配）
    s = s.replace(/([^\n])(\(\d{1,2}\)(?![,，.]\d))/g, '$1\n$2')
    // 题号后统一两个空格
    s = s.replace(/(\(\d{1,2}\))[ \t]*/g, '$1  ')
    // 变量 = 数字
    s = s.replace(/([A-Za-z])\s*=\s*/g, '$1 = ')
    // 一次式：题号独占一行（对齐原图片答案）
    s = s.replace(/(\(\d{1,2}\))  ([A-Za-z]\s*=\s*[^\n（(]+)$/gm, '$1\n$2')
    s = s.replace(/(\(\d{1,2}\))  ([A-Za-z]\s*=\s*[^\n]+)\n/g, '$1\n$2\n')
    // 较长中文叙述小题：题号后换行
    s = s.replace(/(\(\d{1,2}\))  ([\u4e00-\u9fff][^\n]{12,})/g, '$1\n$2')
    // 1/2或5/2 → 1/2 或 5/2
    s = s.replace(/(\d+(?:\/\d+)?)\s*或\s*/g, '$1 或 ')
    // 英文分号后留空；中文分号保持
    s = s.replace(/;([^\s])/g, '; $1')
    // 坐标括号内逗号规范化：(2, 1) → (2,1) 更紧凑；括号外中文逗号不动
    s = s.replace(/\((\d+)\s*,\s*(\d+)\)/g, '($1,$2)')
    s = s.replace(/\s*=\s*/g, ' = ')
    s = s.replace(/(?<=\d)\+(?=\d)/g, ' + ')
    s = s.replace(/(?<=[A-Za-z])\+(?=\d)/g, ' + ')
    // 行尾空白
    s = s.split('\n').map((line) => line.replace(/[ \t]+$/g, '')).join('\n')
    s = s.replace(/\n{3,}/g, '\n\n')
    return s
  }).join('')
}

/** 将题库里的纯文本公式转成 KaTeX（√2 的横线只有公式排版才有，Unicode √ 本身没有） */
function plainAnswerToLatex(text: string): string | null {
  const raw = (text || '').trim()
  if (!raw || raw.includes('[IMG:')) return null
  // 纯选项字母不排版
  if (/^[A-D]$/i.test(raw)) return null
  // 单个变量（斜体）
  if (/^[A-Za-z]$/.test(raw)) return raw
  // 已是 latex
  if (raw.includes('\\sqrt') || raw.includes('\\frac') || raw.includes('\\dfrac') || raw.includes('\\le')) {
    return raw.replace(/^\$+|\$+$/g, '')
  }
  let t = raw
  t = t.replace(/²/g, '^{2}').replace(/³/g, '^{3}')
  // √(1+m²) / √2
  t = t.replace(/√\s*\(([^)]+)\)/g, '\\sqrt{$1}')
  t = t.replace(/(-?\d*)√\s*(\d+(?:\.\d+)?|[A-Za-z])/g, (_, a, b) => (a ? `${a}\\sqrt{${b}}` : `\\sqrt{${b}}`))
  // (1-n)/n√(...) 或 (1-n)/n√(1+m^{2})
  const compound = t.match(/^(\([^)]+\)|[A-Za-z0-9^{}+\-]+)\/([A-Za-z0-9]+)(\\sqrt\{[^}]+\})$/)
  if (compound) {
    return `\\dfrac{${compound[1]}}{${compound[2]}}${compound[3]}`
  }
  // k^2/(2-k^2) 或 k^{2}/(2-k^{2})
  const fracParen = t.match(/^(.+?)\/\((.+)\)$/)
  if (fracParen) {
    return `\\dfrac{${fracParen[1]}}{${fracParen[2]}}`
  }
  // (1-n)/n
  const fracGroup = t.match(/^\(([^)]+)\)\/([A-Za-z0-9]+)$/)
  if (fracGroup) {
    return `\\dfrac{${fracGroup[1]}}{${fracGroup[2]}}`
  }
  // 整段简单分数 1/4、-2/3，或含字母幂的 a/b
  if (/^-?\d+(?:\.\d+)?\/\d+(?:\.\d+)?$/.test(t)) {
    const [a, b] = t.split('/')
    return `\\dfrac{${a}}{${b}}`
  }
  if (/^[A-Za-z0-9^{}\-]+\/[A-Za-z0-9^{}\-+]+$/.test(t) && t.includes('/')) {
    const slash = t.indexOf('/')
    return `\\dfrac{${t.slice(0, slash)}}{${t.slice(slash + 1)}}`
  }
  t = t.replace(/≤/g, '\\le ').replace(/≥/g, '\\ge ').replace(/°/g, '^{\\circ}')
  // 需要公式渲染的特征
  if (/\\sqrt|\\dfrac|\\frac|\\le|\\ge|\^\{/.test(t) || /[≤≥²³]/.test(raw) || /√/.test(raw) || /\//.test(raw)) {
    return t
  }
  return null
}

/** 仅把公式片段交给 KaTeX，中文/普通文本保持表格正文字号 */
const MATH_CHUNK_RE =
  /(\([^)]+\)\/[A-Za-z0-9]+√\([^)]+\)|\([^)]+\)\/[A-Za-z0-9]+|-?\d*√\s*\([^)]+\)|-?\d*√\s*[\dA-Za-z]+(?:\.\d+)?|-?\d+(?:\.\d+)?\/\d+(?:\.\d+)?|[A-Za-z][²]?\/\([A-Za-z0-9²³+\-]+\)|[A-Za-z0-9²³^{}\-]+\/[A-Za-z0-9²³^{}\-+]+|(?<![A-Za-z])[A-Za-z](?=\s*=)|[≤≥]|[²³])/g

function renderKatexChunk(latex: string, key: React.Key) {
  try {
    const html = katex.renderToString(latex, {
      throwOnError: false,
      displayMode: false,
      strict: 'ignore',
      output: 'html',
    })
    return (
      <span
        key={key}
        className="katex-answer"
        style={{
          display: 'inline',
          verticalAlign: 'middle',
          fontSize: 'inherit',
          lineHeight: 'inherit',
        }}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    )
  } catch {
    return <span key={key}>{latex}</span>
  }
}

function renderMathText(text: string, key?: React.Key) {
  const raw = text || ''
  if (!raw) return <span key={key} />

  // 整段已是 latex 或整段可转公式（无中文混排）时整段渲染
  const wholeLatex = plainAnswerToLatex(raw)
  if (wholeLatex && !/[\u4e00-\u9fff]/.test(raw)) {
    return renderKatexChunk(wholeLatex, key ?? 'm')
  }

  // 混排：只渲染公式片段，其余用普通文字（与列表字号一致）
  const parts: React.ReactNode[] = []
  let last = 0
  let mi = 0
  MATH_CHUNK_RE.lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = MATH_CHUNK_RE.exec(raw)) !== null) {
    if (m.index > last) {
      parts.push(<span key={`${key}-t${mi}`}>{raw.slice(last, m.index)}</span>)
    }
    const chunk = m[0]
    const latex = plainAnswerToLatex(chunk)
    parts.push(
      latex
        ? renderKatexChunk(latex, `${key}-m${mi}`)
        : <span key={`${key}-m${mi}`}>{chunk}</span>,
    )
    last = m.index + chunk.length
    mi++
  }
  if (last < raw.length) {
    parts.push(<span key={`${key}-t${mi}`}>{raw.slice(last)}</span>)
  }
  if (!parts.length) {
    return <span key={key}>{raw}</span>
  }
  return <span key={key}>{parts}</span>
}

function renderTextOrMathChunks(text: string, keyPrefix: string) {
  // 按行保留换行，行内拆分公式与正文
  const lines = text.split('\n')
  return lines.map((line, li) => (
    <React.Fragment key={`${keyPrefix}-L${li}`}>
      {li > 0 ? <br /> : null}
      {renderMathText(line, `${keyPrefix}-T${li}`)}
    </React.Fragment>
  ))
}

// 将题目内容中的 [IMG:filename,W,H] 占位符渲染为实际图片（内联，适合表格行）
function renderRichContent(text: string, paperId?: number, opts?: { answerLayout?: boolean }) {
  if (!text) return <span>-</span>
  const src = opts?.answerLayout ? formatAnswerLayout(text) : text
  const parts = src.split(/(\[IMG:[^\]]+\])/g)
  return (
    <span style={{ lineHeight: opts?.answerLayout ? '22px' : '32px', fontSize: 'inherit', whiteSpace: opts?.answerLayout ? 'pre-wrap' : undefined }}>
      {parts.map((part, idx) => {
        const info = parseImgPlaceholder(part)
        if (info && paperId) {
          const url = `/uploads/papers/paper_${paperId}_images/${info.filename}`
          let style: React.CSSProperties = { verticalAlign: 'middle', margin: '0 2px' }
          if (info.hPt > 0 && info.wPt > 0) {
            // 直接用pt值作为px显示，但限制最大高度28px
            const scale = Math.min(1.33, 28 / info.hPt)
            const displayH = info.hPt * scale
            const displayW = info.wPt * scale
            style = { ...style, height: displayH, width: displayW }
          } else {
            style = { ...style, height: 24 }
          }
          return <img key={idx} src={url} alt={info.filename} style={style} />
        }
        return <React.Fragment key={idx}>{renderTextOrMathChunks(part, `r${idx}`)}</React.Fragment>
      })}
    </span>
  )
}

// Tooltip 中渲染完整题目（含图片，中等尺寸）
function renderRichContentTooltip(text: string, paperId?: number, opts?: { answerLayout?: boolean }) {
  if (!text) return <span>-</span>
  const src = opts?.answerLayout ? formatAnswerLayout(text) : text
  const parts = src.split(/(\[IMG:[^\]]+\])/g)
  return (
    <div
      style={{
        maxWidth: 560,
        whiteSpace: 'pre-wrap',
        lineHeight: opts?.answerLayout ? 2.25 : 2.0,
        fontSize: 14,
        padding: opts?.answerLayout ? '2px 0' : undefined,
      }}
    >
      {parts.map((part, idx) => {
        const info = parseImgPlaceholder(part)
        if (info && paperId) {
          const url = `/uploads/papers/paper_${paperId}_images/${info.filename}`
          let style: React.CSSProperties = { verticalAlign: 'middle', margin: '0 3px' }
          if (info.hPt > 0 && info.wPt > 0) {
            if (info.hPt > 50) {
              // 独立大图（如几何图、坐标系）
              const maxH = 180
              const scale = Math.min(1.8, maxH / info.hPt)
              style = { ...style, height: info.hPt * scale, width: info.wPt * scale, display: 'block', margin: '6px 0' }
            } else {
              // 内联公式，直接用 1.33x pt值作为px
              style = { ...style, height: info.hPt * 1.33, width: info.wPt * 1.33 }
            }
          } else {
            style = { ...style, height: 30 }
          }
          return <img key={idx} src={url} alt={info.filename} style={style} />
        }
        return <React.Fragment key={idx}>{renderTextOrMathChunks(part, `tt${idx}`)}</React.Fragment>
      })}
    </div>
  )
}

// 详情模态框中渲染图片（内联公式用行内，大图用块级）
function renderRichContentLarge(text: string, paperId?: number) {
  if (!text) return <span>-</span>
  const parts = text.split(/(\[IMG:[^\]]+\])/g)
  return (
    <div style={{ whiteSpace: 'pre-wrap', lineHeight: '2.2' }}>
      {parts.map((part, idx) => {
        const info = parseImgPlaceholder(part)
        if (info && paperId) {
          const url = `/uploads/papers/paper_${paperId}_images/${info.filename}`
          let style: React.CSSProperties = { verticalAlign: 'middle', margin: '2px 4px' }
          if (info.hPt > 0 && info.wPt > 0) {
            if (info.hPt > 50) {
              // 独立大图（如几何图形）
              const maxH = 240
              const scale = Math.min(2.0, maxH / info.hPt)
              style = { ...style, height: info.hPt * scale, width: info.wPt * scale, display: 'block', margin: '8px 0' }
            } else {
              // 内联公式，直接用 1.5x pt值
              style = { ...style, height: info.hPt * 1.5, width: info.wPt * 1.5 }
            }
          } else {
            style = { ...style, maxHeight: 150, maxWidth: '90%' }
          }
          return <img key={idx} src={url} alt={info.filename} style={style} />
        }
        return <React.Fragment key={idx}>{renderTextOrMathChunks(part, `lg${idx}`)}</React.Fragment>
      })}
    </div>
  )
}

/** 题型展示顺序：选择 → 填空 → 解答 → 证明 */
const TEMPLATE_TYPE_ORDER = ['choice', 'fill', 'answer', 'proof'] as const

function typeOrderRank(qt: string): number {
  const i = (TEMPLATE_TYPE_ORDER as readonly string[]).indexOf(qt)
  return i >= 0 ? i : 99
}

function sortTypeStructure(list: any[] = []): any[] {
  return [...list].sort(
    (a, b) => typeOrderRank(a?.question_type) - typeOrderRank(b?.question_type),
  )
}

/** 结构模板「知识点分值占比」：按题型总分重算占比，并合并题型/一级分类单元格 */
function buildKpRatioTableRows(categoryScoreStats: any, typeStructure: any[] = []): any[] {
  const raw = categoryScoreStats?.ratio_rows
    || categoryScoreStats?.by_category_2
    || []
  if (!raw.length) return []

  // 分母必须用题型结构小计（含未挂载），禁止沿用旧数据里「仅已挂载」算出的 score_ratio
  const typeTotals: Record<string, number> = {}
  for (const t of typeStructure || []) {
    if (t?.question_type) typeTotals[t.question_type] = Number(t.subtotal) || 0
  }
  const fromStats = categoryScoreStats?.type_totals || {}
  for (const [k, v] of Object.entries(fromStats)) {
    const n = Number(v)
    if (!Number.isNaN(n) && n > 0) typeTotals[k] = n
  }

  const typeRank = (qt: string) => typeOrderRank(qt)

  const rows = [...raw]
    .map((r: any) => {
      const qtype = r.question_type || 'answer'
      const score = Number(r.score_sum) || 0
      const denom = typeTotals[qtype] || 0
      return {
        ...r,
        question_type: qtype,
        category_1: r.category_1 || '未分类',
        category_2: r.category_2 === '无二级分类' ? '' : (r.category_2 || ''),
        score_sum: score,
        score_ratio: denom > 0 ? score / denom : 0,
      }
    })
    .sort((a: any, b: any) => {
      const d = typeRank(a.question_type) - typeRank(b.question_type)
      if (d !== 0) return d
      const c1 = String(a.category_1).localeCompare(String(b.category_1), 'zh')
      if (c1 !== 0) return c1
      return String(a.category_2 || '').localeCompare(String(b.category_2 || ''), 'zh')
    })

  const tSpan = new Array(rows.length).fill(1)
  const cSpan = new Array(rows.length).fill(1)
  for (let i = rows.length - 1; i > 0; i--) {
    if (rows[i].question_type === rows[i - 1].question_type) {
      tSpan[i - 1] += tSpan[i]
      tSpan[i] = 0
    }
    if (
      rows[i].question_type === rows[i - 1].question_type
      && rows[i].category_1 === rows[i - 1].category_1
    ) {
      cSpan[i - 1] += cSpan[i]
      cSpan[i] = 0
    }
  }
  return rows.map((r: any, i: number) => ({
    ...r,
    _typeSpan: tSpan[i],
    _cat1Span: cSpan[i],
  }))
}

export default function QuestionBank({ defaultTab = 'papers' }: { defaultTab?: 'papers' | 'real-questions' | 'mock-questions' | 'ai-questions' }) {
  // 试卷相关
  const [papers, setPapers] = useState<any[]>([])
  const [papersLoading, setPapersLoading] = useState(false)
  const [uploadModalVisible, setUploadModalVisible] = useState(false)
  const [uploadForm] = Form.useForm()
  const [uploading, setUploading] = useState(false)
  const [uploadFile, setUploadFile] = useState<any>(null)
  const [editPaperModalVisible, setEditPaperModalVisible] = useState(false)
  const [editPaperForm] = Form.useForm()
  const [editingPaper, setEditingPaper] = useState<any>(null)
  const [editPaperSaving, setEditPaperSaving] = useState(false)

  // 题目相关
  const [questions, setQuestions] = useState<any[]>([])
  const [questionsLoading, setQuestionsLoading] = useState(false)
  const [totalQuestions, setTotalQuestions] = useState(0)
  const [realTotal, setRealTotal] = useState(0)
  const [mockTotal, setMockTotal] = useState(0)
  const [currentPage, setCurrentPage] = useState(1)
  const [pageSize] = useState(20)
  const [filterBankType, setFilterBankType] = useState<'real' | 'mock' | 'ai'>(defaultTab === 'mock-questions' ? 'mock' : defaultTab === 'ai-questions' ? 'ai' : 'real')
  const [filterPaperId, setFilterPaperId] = useState<number | undefined>()
  const [filterType, setFilterType] = useState<string | undefined>()
  const [filterDifficulty, setFilterDifficulty] = useState<number | undefined>()
  const [filterAbilityDimension, setFilterAbilityDimension] = useState<string | undefined>()
  const [filterKeyword, setFilterKeyword] = useState<string | undefined>()
  const [filterLinkStatus, setFilterLinkStatus] = useState<string | undefined>()
  const [linkedCount, setLinkedCount] = useState(0)
  const [linkRate, setLinkRate] = useState(0)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [activeTab, setActiveTab] = useState(defaultTab)

  // 知识点下拉
  const [kpOptions, setKpOptions] = useState<Array<{ value: string; label: string }>>([])
  const [kpSearching, setKpSearching] = useState(false)

  // 智能关联
  const [linkModalVisible, setLinkModalVisible] = useState(false)
  const [linkScope, setLinkScope] = useState<'paper' | 'unlinked' | 'selected'>('unlinked')
  const [linkTaskId, setLinkTaskId] = useState<number | null>(null)
  const [linkTaskProgress, setLinkTaskProgress] = useState(0)
  const [linkTaskStatus, setLinkTaskStatus] = useState<string>('')
  const [linkStarting, setLinkStarting] = useState(false)
  const [confirmDrawerVisible, setConfirmDrawerVisible] = useState(false)
  const [suggestions, setSuggestions] = useState<any[]>([])
  const [suggestionEdits, setSuggestionEdits] = useState<Record<number, { action: string; kp_id?: string }>>({})
  const [confirmSaving, setConfirmSaving] = useState(false)
  const [batchKpId, setBatchKpId] = useState<string | undefined>()
  const [rewriteImgLoading, setRewriteImgLoading] = useState(false)
  const [answerRewriteTaskId, setAnswerRewriteTaskId] = useState<number | null>(null)
  const [answerRewriteProgress, setAnswerRewriteProgress] = useState(0)
  const [answerRewriteStatus, setAnswerRewriteStatus] = useState('')
  const [answerRewriteDrawerVisible, setAnswerRewriteDrawerVisible] = useState(false)
  const [answerRewriteSuggestions, setAnswerRewriteSuggestions] = useState<any[]>([])
  const [answerRewriteEdits, setAnswerRewriteEdits] = useState<Record<number, string>>({})
  const [answerRewriteSaving, setAnswerRewriteSaving] = useState(false)

  // 能力维度 AI 标注
  const [abilityModalVisible, setAbilityModalVisible] = useState(false)
  const [abilityScope, setAbilityScope] = useState<'unlabeled' | 'paper' | 'selected'>('unlabeled')
  const [abilityTaskId, setAbilityTaskId] = useState<number | null>(null)
  const [abilityTaskProgress, setAbilityTaskProgress] = useState(0)
  const [abilityTaskStatus, setAbilityTaskStatus] = useState('')
  const [abilityStarting, setAbilityStarting] = useState(false)
  const [abilityDrawerVisible, setAbilityDrawerVisible] = useState(false)
  const [abilitySuggestions, setAbilitySuggestions] = useState<any[]>([])
  const [abilityEdits, setAbilityEdits] = useState<Record<number, { action: string; ability_dimension?: string }>>({})
  const [abilitySaving, setAbilitySaving] = useState(false)

  // 编辑题目
  const [editDrawerVisible, setEditDrawerVisible] = useState(false)
  const [editingQuestion, setEditingQuestion] = useState<any>(null)
  const [editForm] = Form.useForm()

  // 查看题目详情
  const [detailVisible, setDetailVisible] = useState(false)
  const [detailQuestion, setDetailQuestion] = useState<any>(null)

  // 结构模板
  const [templateDrawerVisible, setTemplateDrawerVisible] = useState(false)
  const [templateDetail, setTemplateDetail] = useState<any>(null)
  const [templateListVisible, setTemplateListVisible] = useState(false)
  const [templateList, setTemplateList] = useState<any[]>([])
  const [templateListLoading, setTemplateListLoading] = useState(false)
  const [buildLoadingId, setBuildLoadingId] = useState<number | null>(null)
  const [selectedPaperKeys, setSelectedPaperKeys] = useState<React.Key[]>([])
  const [buildSelectedLoading, setBuildSelectedLoading] = useState(false)
  const [viewAverageLoading, setViewAverageLoading] = useState(false)
  const [templateScoreSavingId, setTemplateScoreSavingId] = useState<number | null>(null)
  const [templateTypeScoreSaving, setTemplateTypeScoreSaving] = useState<string | null>(null)

  const searchKnowledgePoints = async (keyword?: string) => {
    setKpSearching(true)
    try {
      const res = await knowledgeApi.listPoints({
        page: 1,
        page_size: 100,
        keyword: keyword || undefined,
      })
      const items = res.data?.items || []
      setKpOptions(items.map((p: any) => ({
        value: p.id,
        label: `${p.name}${p.category_1 ? `（${p.category_1}）` : ''}`,
      })))
    } catch {
      // ignore
    }
    setKpSearching(false)
  }

  const fetchPapers = async () => {
    setPapersLoading(true)
    try {
      const res = await questionApi.listPapers()
      setPapers(res.data || [])
    } catch {
      message.error('获取试卷列表失败')
    }
    setPapersLoading(false)
  }

  const openBuiltTemplate = (data: any, opts?: { silent?: boolean }) => {
    setTemplateDetail(data)
    setTemplateDrawerVisible(true)
    if (!opts?.silent) {
      if (data?.status === 'ready') {
        message.success(
          `结构模板已生成（完整，来源 ${data.build_meta?.paper_count || data.source_paper_ids?.length || 1} 套）`
        )
      } else {
        const miss = data?.build_meta?.missing_score_count || 0
        message.warning(
          miss > 0
            ? `模板已打开：尚有 ${miss} 题缺分值，可在「题目明细」中补填`
            : '结构模板已生成，但不完整，不可设为默认',
        )
      }
    }
    fetchPapers()
  }

  /** 单卷模板：改分值 → 写回题目 → 重建模板统计 */
  const handleTemplateScoreSave = async (row: any, nextScore: number | null) => {
    const prev = row.score == null ? null : Number(row.score)
    const next = nextScore == null || Number.isNaN(Number(nextScore)) ? null : Number(nextScore)
    if (prev === next) return
    const paperIds = templateDetail?.source_paper_ids || []
    if (paperIds.length !== 1) {
      message.warning('仅单卷模板支持在明细中改分')
      return
    }
    setTemplateScoreSavingId(row.question_id)
    try {
      await questionApi.updateQuestion(row.question_id, { score: next })
      const res = await questionApi.buildTemplate(paperIds[0])
      openBuiltTemplate(res.data, { silent: true })
      message.success(
        next == null
          ? `第 ${row.question_number ?? row.question_id} 题分值已清空`
          : `第 ${row.question_number ?? row.question_id} 题已设为 ${next} 分`,
      )
    } catch (e: any) {
      message.error(e.response?.data?.detail || '更新分值失败')
    }
    setTemplateScoreSavingId(null)
  }

  /** 单卷模板：题型结构「每题分值」→ 覆盖该题型下全部题目明细分值；空值不覆盖 */
  const handleTypeScoreEachSave = async (qtype: string, nextScore: number) => {
    if (nextScore == null || Number.isNaN(Number(nextScore))) return
    const paperIds = templateDetail?.source_paper_ids || []
    if (paperIds.length !== 1) {
      message.warning('仅单卷模板支持按题型统一改分')
      return
    }
    const rows = (templateDetail.question_rows || []).filter(
      (r: any) => r.question_type === qtype,
    )
    if (!rows.length) {
      message.warning('该题型下暂无题目')
      return
    }
    const target = Number(nextScore)
    const prevEach = (templateDetail.type_structure || []).find(
      (t: any) => t.question_type === qtype,
    )?.score_each
    const allSame =
      prevEach != null
      && Number(prevEach) === target
      && rows.every((r: any) => r.score != null && Number(r.score) === target)
    if (allSame) return

    const typeLabel = questionTypeLabels[qtype]?.label || qtype
    setTemplateTypeScoreSaving(qtype)
    try {
      await Promise.all(
        rows.map((r: any) => questionApi.updateQuestion(r.question_id, { score: target })),
      )
      const res = await questionApi.buildTemplate(paperIds[0])
      openBuiltTemplate(res.data, { silent: true })
      message.success(`已将「${typeLabel}」共 ${rows.length} 题统一为每题 ${target} 分`)
    } catch (e: any) {
      message.error(e.response?.data?.detail || '按题型更新分值失败')
    }
    setTemplateTypeScoreSaving(null)
  }

  const handleBuildTemplate = async (paperId: number) => {
    setBuildLoadingId(paperId)
    try {
      const res = await questionApi.buildTemplate(paperId)
      openBuiltTemplate(res.data)
    } catch (e: any) {
      message.error(e.response?.data?.detail || '生成模板失败')
    }
    setBuildLoadingId(null)
  }

  const handleBuildFromSelected = async () => {
    const ids = selectedPaperKeys.map(Number).filter(Boolean)
    if (!ids.length) {
      message.warning('请先勾选至少一套试卷')
      return
    }
    setBuildSelectedLoading(true)
    try {
      const res = await questionApi.buildTemplateFromPapers({ paper_ids: ids })
      openBuiltTemplate(res.data)
    } catch (e: any) {
      message.error(e.response?.data?.detail || '生成模板失败')
    }
    setBuildSelectedLoading(false)
  }

  const openTemplateDetail = async (templateId: number) => {
    try {
      const res = await questionApi.getTemplate(templateId)
      setTemplateDetail(res.data)
      setTemplateDrawerVisible(true)
    } catch (e: any) {
      message.error(e.response?.data?.detail || '获取模板失败')
    }
  }

  const fetchTemplateList = async () => {
    setTemplateListLoading(true)
    try {
      const res = await questionApi.listTemplates({ subject: '数学' })
      setTemplateList(res.data || [])
      setTemplateListVisible(true)
    } catch (e: any) {
      message.error(e.response?.data?.detail || '获取模板列表失败')
    }
    setTemplateListLoading(false)
  }

  /** 查看平均结构模板：有勾选则按所选组合；未勾选则打开最近一份多套平均模板 */
  const handleViewAverageTemplate = async () => {
    const ids = selectedPaperKeys.map(Number).filter(Boolean)
    setViewAverageLoading(true)
    try {
      const res = ids.length >= 2
        ? await questionApi.getTemplateBySource(ids)
        : await questionApi.getLatestAverageTemplate()
      setTemplateDetail(res.data)
      setTemplateDrawerVisible(true)
    } catch (e: any) {
      const detail = e.response?.data?.detail
      message.error(
        (typeof detail === 'string' ? detail : null)
        || '尚未生成平均模板，请先勾选多套试卷并点击「从所选试卷生成模板」',
      )
    }
    setViewAverageLoading(false)
  }

  const handleSetDefaultTemplate = async (id: number) => {
    try {
      await questionApi.setDefaultTemplate(id)
      message.success('已设为默认模板')
      const res = await questionApi.getTemplate(id)
      setTemplateDetail(res.data)
      fetchPapers()
      if (templateListVisible) fetchTemplateList()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '设置默认失败')
    }
  }

  const handleUnsetDefaultTemplate = async (id: number) => {
    try {
      await questionApi.unsetDefaultTemplate(id)
      message.success('已取消默认')
      fetchPapers()
      if (templateListVisible) fetchTemplateList()
      if (templateDetail?.id === id) {
        const res = await questionApi.getTemplate(id)
        setTemplateDetail(res.data)
      }
    } catch (e: any) {
      message.error(e.response?.data?.detail || '取消默认失败')
    }
  }

  const handleDeleteTemplate = async (id: number) => {
    try {
      await questionApi.deleteTemplate(id)
      message.success('模板已删除')
      setTemplateList(prev => prev.filter(t => t.id !== id))
      fetchPapers()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '删除失败')
    }
  }

  const fetchQuestions = async (page = currentPage, bankType = filterBankType) => {
    setQuestionsLoading(true)
    try {
      const params: any = { page, page_size: pageSize, bank_type: bankType }
      if (filterPaperId) params.exam_paper_id = filterPaperId
      if (filterType) params.question_type = filterType
      if (filterDifficulty) params.difficulty = filterDifficulty
      if (filterAbilityDimension) params.ability_dimension = filterAbilityDimension
      if (filterKeyword) params.keyword = filterKeyword
      if (filterLinkStatus) params.link_status = filterLinkStatus
      const res = await questionApi.listQuestions(params)
      setQuestions(res.data?.items || [])
      setTotalQuestions(res.data?.total || 0)
      setLinkedCount(res.data?.linked_count ?? 0)
      setLinkRate(res.data?.link_rate ?? 0)
    } catch {
      message.error('获取题目列表失败')
    }
    setQuestionsLoading(false)
  }

  const fetchQuestionCounts = async () => {
    try {
      const [realRes, mockRes] = await Promise.all([
        questionApi.listQuestions({ page: 1, page_size: 1, bank_type: 'real' }),
        questionApi.listQuestions({ page: 1, page_size: 1, bank_type: 'mock' }),
      ])
      setRealTotal(realRes.data?.total || 0)
      setMockTotal(mockRes.data?.total || 0)
    } catch {
      // ignore count errors
    }
  }

  useEffect(() => {
    fetchPapers()
    fetchQuestionCounts()
    searchKnowledgePoints()
  }, [])
  useEffect(() => {
    fetchQuestions(1)
    setCurrentPage(1)
    setSelectedRowKeys([])
  }, [filterBankType, filterPaperId, filterType, filterDifficulty, filterAbilityDimension, filterKeyword, filterLinkStatus])

  // 轮询：如果有试卷正在解析，自动刷新直到完成
  useEffect(() => {
    const hasParsing = papers.some(p => p.parse_status === 'parsing' || p.parse_status === 'pending')
    if (!hasParsing) return
    const timer = setInterval(async () => {
      try {
        const res = await questionApi.listPapers()
        const list = res.data || []
        setPapers(list)
        const stillParsing = list.some((p: any) => p.parse_status === 'parsing' || p.parse_status === 'pending')
        if (!stillParsing) {
          clearInterval(timer)
          fetchQuestions()
          fetchQuestionCounts()
        }
      } catch { /* ignore */ }
    }, 3000)
    return () => clearInterval(timer)
  }, [papers])

  useEffect(() => {
    setActiveTab(defaultTab)
    if (defaultTab === 'real-questions' || defaultTab === 'mock-questions' || defaultTab === 'ai-questions') {
      setFilterPaperId(undefined)
      setFilterType(undefined)
      setFilterDifficulty(undefined)
      setFilterKeyword(undefined)
      setFilterLinkStatus(undefined)
      setSelectedRowKeys([])
      setFilterBankType(defaultTab === 'real-questions' ? 'real' : defaultTab === 'ai-questions' ? 'ai' : 'mock')
    }
  }, [defaultTab])

  const handleTabChange = (key: 'papers' | 'real-questions' | 'mock-questions' | 'ai-questions') => {
    setActiveTab(key)
    if (key === 'real-questions' || key === 'mock-questions' || key === 'ai-questions') {
      setFilterPaperId(undefined)
      setFilterType(undefined)
      setFilterDifficulty(undefined)
      setFilterKeyword(undefined)
      setFilterLinkStatus(undefined)
      setSelectedRowKeys([])
      setFilterBankType(key === 'real-questions' ? 'real' : key === 'ai-questions' ? 'ai' : 'mock')
    }
  }

  const openEditPaper = (record: any) => {
    setEditingPaper(record)
    editPaperForm.setFieldsValue({
      title: record.title,
      paper_type: record.paper_type || 'real',
      grade: record.grade || undefined,
      year: record.year || undefined,
      region: record.region || undefined,
    })
    setEditPaperModalVisible(true)
  }

  const handleEditPaper = async () => {
    if (!editingPaper?.id) return
    try {
      const values = await editPaperForm.validateFields()
      setEditPaperSaving(true)
      await questionApi.updatePaper(editingPaper.id, {
        title: values.title?.trim(),
        paper_type: values.paper_type,
        grade: values.grade || null,
        year: values.year || null,
        region: values.region || null,
      } as any)
      message.success('试卷已更新')
      setEditPaperModalVisible(false)
      setEditingPaper(null)
      editPaperForm.resetFields()
      fetchPapers()
      fetchQuestionCounts()
    } catch (e: any) {
      if (e?.errorFields) return
      message.error(e.response?.data?.detail || '更新失败')
    }
    setEditPaperSaving(false)
  }

  const handleUpload = async () => {
    const values = await uploadForm.validateFields()
    if (!uploadFile) {
      message.warning('请选择试卷文件')
      return
    }
    setUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', uploadFile)
      formData.append('title', values.title)
      formData.append('paper_type', values.paper_type || 'real')
      if (values.grade) formData.append('grade', values.grade)
      if (values.year) formData.append('year', values.year)
      if (values.region) formData.append('region', values.region)

      await questionApi.uploadPaper(formData)
      message.success('试卷上传成功，正在解析中...')
      setUploadModalVisible(false)
      uploadForm.resetFields()
      setUploadFile(null)
      fetchPapers()
      setTimeout(() => { fetchPapers(); fetchQuestions(); fetchQuestionCounts() }, 3000)
    } catch (e: any) {
      message.error(e.response?.data?.detail || '上传失败')
    }
    setUploading(false)
  }

  const handleDeletePaper = async (id: number) => {
    await questionApi.deletePaper(id)
    message.success('已删除试卷')
    fetchPapers()
    fetchQuestions()
    fetchQuestionCounts()
  }

  const handleClearByType = async (bankType: 'real' | 'mock') => {
    try {
      await questionApi.clearAll(bankType)
      message.success(bankType === 'real' ? '已清除真题题库' : '已清除模拟题库')
      fetchPapers()
      fetchQuestions()
      fetchQuestionCounts()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '清除失败')
    }
  }

  const handleReparsePaper = async (id: number) => {
    await questionApi.reparsePaper(id)
    message.success('已启动重新解析')
    setTimeout(() => { fetchPapers(); fetchQuestions() }, 3000)
  }

  const handleEditQuestion = (record: any) => {
    setEditingQuestion(record)
    if (record.primary_kp_id && record.primary_kp_name) {
      setKpOptions(prev => {
        if (prev.some(o => o.value === record.primary_kp_id)) return prev
        return [{ value: record.primary_kp_id, label: record.primary_kp_name }, ...prev]
      })
    }
    editForm.setFieldsValue({
      question_type: record.question_type,
      question_number: record.question_number,
      content: record.content,
      answer: record.answer,
      analysis: record.analysis,
      difficulty: record.difficulty,
      score: record.score,
      ability_dimension: record.ability_dimension,
      primary_kp_id: record.primary_kp_id || undefined,
    })
    setEditDrawerVisible(true)
  }

  const handleSaveQuestion = async () => {
    const values = await editForm.validateFields()
    const data: any = {
      question_type: values.question_type,
      question_number: values.question_number,
      content: values.content,
      answer: values.answer || null,
      analysis: values.analysis || null,
      difficulty: values.difficulty,
      score: values.score || null,
      ability_dimension: values.ability_dimension || null,
      primary_kp_id: values.primary_kp_id || null,
    }
    try {
      await questionApi.updateQuestion(editingQuestion.id, data)
      message.success('更新成功')
      setEditDrawerVisible(false)
      fetchQuestions()
      fetchPapers()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '更新失败')
    }
  }

  const pollLinkTask = async (taskId: number) => {
    setLinkTaskId(taskId)
    setLinkTaskProgress(0)
    setLinkTaskStatus('running')
    for (let i = 0; i < 120; i++) {
      await new Promise(r => setTimeout(r, 1500))
      try {
        const res = await questionApi.getKpLinkTask(taskId)
        const task = res.data
        setLinkTaskProgress(task.progress || 0)
        setLinkTaskStatus(task.status)
        if (task.status === 'completed') {
          const suggested = task.result_summary?.suggested
          if (suggested === 0) {
            message.warning(task.error_message || '任务完成但无有效建议，请检查模型配置或手动改选')
          } else {
            message.success(`智能关联完成（有效建议 ${suggested} 条），请确认结果`)
          }
          await openConfirmDrawer(taskId)
          return
        }
        if (task.status === 'failed') {
          Modal.error({
            title: '智能关联失败',
            width: 560,
            content: (
              <div>
                <p>{task.error_message || '未知错误'}</p>
                <p style={{ color: '#666', marginTop: 8 }}>
                  智能关联与知识抽取共用「系统配置 → 运行设置」中的大模型。
                  若提示模型名无效，请改为 deepseek-v4-flash 或 deepseek-v4-pro 后重试。
                </p>
              </div>
            ),
          })
          return
        }
      } catch {
        // continue polling
      }
    }
    message.warning('任务仍在运行，可稍后筛选「待确认」查看')
  }

  const handleStartKpLink = async () => {
    if (linkScope === 'paper' && !filterPaperId) {
      message.warning('请先在列表上方选择一套试卷')
      return
    }
    if (linkScope === 'selected' && selectedRowKeys.length === 0) {
      message.warning('请先勾选题目')
      return
    }
    setLinkStarting(true)
    try {
      const payload: any = {
        only_unlinked: linkScope === 'unlinked',
        bank_type: filterBankType,
      }
      if (linkScope === 'paper') {
        payload.exam_paper_id = filterPaperId
        payload.only_unlinked = true
      } else if (linkScope === 'selected') {
        payload.question_ids = selectedRowKeys.map(Number)
        payload.only_unlinked = false
      } else if (filterPaperId) {
        payload.exam_paper_id = filterPaperId
      }
      const res = await questionApi.startKpLink(payload)
      message.success(`任务已启动 #${res.data.id}`)
      setLinkModalVisible(false)
      pollLinkTask(res.data.id)
    } catch (e: any) {
      message.error(e.response?.data?.detail || '启动失败')
    }
    setLinkStarting(false)
  }

  const openConfirmDrawer = async (taskId?: number) => {
    try {
      const res = await questionApi.listKpLinkSuggestions({
        task_id: taskId,
        status: 'pending',
      })
      const items = res.data || []
      setSuggestions(items)
      const edits: Record<number, { action: string; kp_id?: string }> = {}
      items.forEach((s: any) => {
        edits[s.id] = { action: s.suggested_kp_id ? 'accept' : 'reject', kp_id: s.suggested_kp_id }
      })
      setSuggestionEdits(edits)
      setConfirmDrawerVisible(true)
    } catch {
      message.error('获取待确认建议失败')
    }
  }

  const handleAcceptAllHigh = () => {
    setSuggestionEdits(prev => {
      const next = { ...prev }
      suggestions.forEach((s: any) => {
        if (s.confidence === 'high' && s.suggested_kp_id) {
          next[s.id] = { action: 'accept', kp_id: s.suggested_kp_id }
        }
      })
      return next
    })
    message.info('已将高置信建议设为采用')
  }

  const handleConfirmSuggestions = async () => {
    const items = suggestions.map((s: any) => {
      const edit = suggestionEdits[s.id] || { action: 'reject' }
      return {
        suggestion_id: s.id,
        action: edit.action,
        kp_id: edit.action === 'modify' ? edit.kp_id : undefined,
      }
    }).filter(it => it.action)
    if (items.length === 0) {
      message.warning('没有可确认的项')
      return
    }
    setConfirmSaving(true)
    try {
      const res = await questionApi.confirmKpLink({ items })
      message.success(res.data?.message || '确认完成')
      setConfirmDrawerVisible(false)
      setSelectedRowKeys([])
      fetchQuestions()
      fetchPapers()
      fetchQuestionCounts()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '确认失败')
    }
    setConfirmSaving(false)
  }

  const openAnswerRewriteDrawer = async (taskId?: number) => {
    try {
      const res = await questionApi.listAnswerRewriteSuggestions({
        task_id: taskId,
        status: 'pending',
      })
      const items = res.data || []
      setAnswerRewriteSuggestions(items)
      const edits: Record<number, string> = {}
      items.forEach((s: any) => {
        edits[s.id] = s.suggested_answer ? 'accept' : 'reject'
      })
      setAnswerRewriteEdits(edits)
      setAnswerRewriteDrawerVisible(true)
      if (items.length === 0) {
        message.info('暂无待确认的答案转写建议')
      }
    } catch {
      message.error('获取答案转写建议失败')
    }
  }

  const pollAnswerRewriteTask = async (taskId: number) => {
    setAnswerRewriteTaskId(taskId)
    setAnswerRewriteStatus('running')
    setAnswerRewriteProgress(0)
    for (let i = 0; i < 240; i++) {
      await new Promise(r => setTimeout(r, 1500))
      try {
        const res = await questionApi.getAnswerRewriteTask(taskId)
        const task = res.data
        setAnswerRewriteProgress(task.progress || 0)
        setAnswerRewriteStatus(task.status)
        if (task.status === 'completed') {
          const suggested = task.result_summary?.suggested
          if (suggested === 0) {
            message.warning(task.error_message || '任务完成但无可确认建议')
          } else {
            message.success(`答案转写完成（${suggested} 条建议），请确认后再写入`)
          }
          await openAnswerRewriteDrawer(taskId)
          setRewriteImgLoading(false)
          return
        }
        if (task.status === 'failed') {
          message.error(task.error_message || '答案转写任务失败')
          setRewriteImgLoading(false)
          return
        }
      } catch {
        // continue
      }
    }
    message.warning('任务仍在运行，可稍后从「待确认结果 → 答案转写」查看')
    setRewriteImgLoading(false)
  }

  const handleBatchRewriteImageAnswers = () => {
    const selectedIds = selectedRowKeys.map(Number).filter(Boolean)
    const scopeLabel = selectedIds.length
      ? `已选 ${selectedIds.length} 题`
      : filterPaperId
        ? `当前试卷（ID ${filterPaperId}）`
        : `当前题库（${filterBankType === 'real' ? '真题' : '模拟'}）`
    Modal.confirm({
      title: '批量转写图片答案为文本',
      content: (
        <div>
          <p>范围：{scopeLabel}中，答案含公式图片的题目。</p>
          <p>识别结果先进入右侧「待确认」列表，对比原答案与转写结果后，采用才会写入题库。</p>
          <p style={{ color: '#fa8c16', marginBottom: 0 }}>
            通用 OCR 对复杂公式仍可能不准；识别失败会保留原图。首次加载引擎可能较慢。
          </p>
        </div>
      ),
      okText: '开始识别',
      cancelText: '取消',
      onOk: async () => {
        setRewriteImgLoading(true)
        try {
          const payload: Record<string, unknown> = {}
          if (selectedIds.length) payload.question_ids = selectedIds
          else if (filterPaperId) payload.exam_paper_id = filterPaperId
          else payload.bank_type = filterBankType
          const res = await questionApi.startAnswerRewrite(payload as any)
          message.success(`任务已启动 #${res.data.id}，完成后请确认`)
          pollAnswerRewriteTask(res.data.id)
        } catch (e: any) {
          const status = e.response?.status
          const detail = e.response?.data?.detail
          if (status === 404) {
            message.error('接口不存在，请重启后端服务后再试')
          } else {
            message.error(detail || '启动失败')
          }
          setRewriteImgLoading(false)
        }
      },
    })
  }

  const handleConfirmAnswerRewrite = async () => {
    const items = answerRewriteSuggestions.map((s: any) => ({
      suggestion_id: s.id,
      action: answerRewriteEdits[s.id] || 'reject',
    }))
    if (items.length === 0) {
      message.warning('没有可确认的项')
      return
    }
    setAnswerRewriteSaving(true)
    try {
      const res = await questionApi.confirmAnswerRewrite({ items })
      const d = res.data || {}
      message.success(`已采用 ${d.accepted || 0} 条，拒绝 ${d.rejected || 0} 条`)
      setAnswerRewriteDrawerVisible(false)
      fetchQuestions()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '确认失败')
    }
    setAnswerRewriteSaving(false)
  }

  const handleAcceptAllAnswerRewrite = () => {
    setAnswerRewriteEdits(prev => {
      const next = { ...prev }
      answerRewriteSuggestions.forEach((s: any) => {
        if (s.suggested_answer) next[s.id] = 'accept'
      })
      return next
    })
    message.info('已全部设为采用')
  }

  const openAbilityDrawer = async (taskId?: number) => {
    try {
      const res = await questionApi.listAbilityLabelSuggestions({
        task_id: taskId,
        status: 'pending',
      })
      const items = res.data || []
      setAbilitySuggestions(items)
      const edits: Record<number, { action: string; ability_dimension?: string }> = {}
      items.forEach((s: any) => {
        edits[s.id] = {
          action: s.suggested_dimension ? 'accept' : 'reject',
          ability_dimension: s.suggested_dimension,
        }
      })
      setAbilityEdits(edits)
      setAbilityDrawerVisible(true)
      if (items.length === 0) {
        message.info('暂无待确认的能力维度建议')
      }
    } catch {
      message.error('获取能力维度建议失败')
    }
  }

  const pollAbilityTask = async (taskId: number) => {
    setAbilityTaskId(taskId)
    setAbilityTaskStatus('running')
    setAbilityTaskProgress(0)
    for (let i = 0; i < 240; i++) {
      await new Promise(r => setTimeout(r, 1500))
      try {
        const res = await questionApi.getAbilityLabelTask(taskId)
        const task = res.data
        setAbilityTaskProgress(task.progress || 0)
        setAbilityTaskStatus(task.status)
        if (task.status === 'completed') {
          const suggested = task.result_summary?.suggested
          if (suggested === 0) {
            message.warning(task.error_message || '任务完成但无有效标注')
          } else {
            message.success(`能力维度标注完成，已标注 ${suggested} 道题目`)
          }
          fetchQuestions()
          return
        }
        if (task.status === 'failed') {
          Modal.error({
            title: '能力维度标注失败',
            width: 560,
            content: (
              <div>
                <p>{task.error_message || '未知错误'}</p>
                <p style={{ color: '#666', marginTop: 8 }}>
                  与知识抽取共用「系统配置 → 运行设置」中的大模型。
                </p>
              </div>
            ),
          })
          return
        }
      } catch {
        // continue
      }
    }
    message.warning('任务仍在运行，可稍后从「待确认结果 → 能力维度」查看')
  }

  const handleStartAbilityLabel = async () => {
    if (abilityScope === 'paper' && !filterPaperId) {
      message.warning('请先在列表上方选择一套试卷')
      return
    }
    if (abilityScope === 'selected' && selectedRowKeys.length === 0) {
      message.warning('请先勾选题目')
      return
    }
    setAbilityStarting(true)
    try {
      const payload: any = {
        only_unlabeled: abilityScope === 'unlabeled',
        bank_type: filterBankType,
      }
      if (abilityScope === 'paper') {
        payload.exam_paper_id = filterPaperId
        payload.only_unlabeled = false
      } else if (abilityScope === 'selected') {
        payload.question_ids = selectedRowKeys.map(Number)
        payload.only_unlabeled = false
      } else if (filterPaperId) {
        payload.exam_paper_id = filterPaperId
      }
      const res = await questionApi.startAbilityLabel(payload)
      message.success(`任务已启动 #${res.data.id}`)
      setAbilityModalVisible(false)
      pollAbilityTask(res.data.id)
    } catch (e: any) {
      message.error(e.response?.data?.detail || '启动失败')
    }
    setAbilityStarting(false)
  }

  const handleAcceptAllAbilityHigh = () => {
    setAbilityEdits(prev => {
      const next = { ...prev }
      abilitySuggestions.forEach((s: any) => {
        if (s.confidence === 'high' && s.suggested_dimension) {
          next[s.id] = { action: 'accept', ability_dimension: s.suggested_dimension }
        }
      })
      return next
    })
    message.info('已将高置信建议设为采用')
  }

  const handleConfirmAbilityLabel = async () => {
    const items = abilitySuggestions.map((s: any) => {
      const edit = abilityEdits[s.id] || { action: 'reject' }
      return {
        suggestion_id: s.id,
        action: edit.action,
        ability_dimension: edit.action === 'modify' ? edit.ability_dimension : undefined,
      }
    }).filter(it => it.action)
    if (!items.length) {
      message.warning('没有可确认的项')
      return
    }
    setAbilitySaving(true)
    try {
      const res = await questionApi.confirmAbilityLabel({ items })
      const d = res.data || {}
      message.success(
        `已采用 ${d.accepted || 0} 条，改选 ${d.modified || 0} 条，拒绝 ${d.rejected || 0} 条`,
      )
      setAbilityDrawerVisible(false)
      fetchQuestions()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '确认失败')
    }
    setAbilitySaving(false)
  }

  const handleBatchSetPrimaryKp = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先勾选题目')
      return
    }
    if (!batchKpId) {
      message.warning('请选择主知识点')
      return
    }
    try {
      await questionApi.batchSetPrimaryKp({
        question_ids: selectedRowKeys.map(Number),
        primary_kp_id: batchKpId,
      })
      message.success('批量挂载成功')
      setBatchKpId(undefined)
      setSelectedRowKeys([])
      fetchQuestions()
      fetchPapers()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '批量挂载失败')
    }
  }

  const handleDeleteQuestion = async (id: number) => {
    await questionApi.deleteQuestion(id)
    message.success('已删除')
    setSelectedRowKeys(keys => keys.filter(k => Number(k) !== id))
    fetchQuestions()
    fetchQuestionCounts()
    fetchPapers()
  }

  const handleBatchDeleteQuestions = async () => {
    const ids = selectedRowKeys.map(Number).filter(Boolean)
    if (!ids.length) {
      message.warning('请先勾选要删除的题目')
      return
    }
    try {
      const res = await questionApi.batchDeleteQuestions({ question_ids: ids })
      message.success(res.data?.message || `已删除 ${ids.length} 题`)
      setSelectedRowKeys([])
      fetchQuestions()
      fetchQuestionCounts()
      fetchPapers()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '批量删除失败')
    }
  }

  const questionTypeLabels: Record<string, { label: string; color: string }> = {
    choice: { label: '选择题', color: 'blue' },
    fill: { label: '填空题', color: 'green' },
    answer: { label: '解答题', color: 'orange' },
    proof: { label: '证明题', color: 'purple' },
  }

  const parseStatusLabels: Record<string, { label: string; color: string }> = {
    pending: { label: '等待解析', color: 'default' },
    parsing: { label: '解析中', color: 'processing' },
    parsed: { label: '已解析', color: 'success' },
    failed: { label: '解析失败', color: 'error' },
  }

  const abilityDimensionOptions = ['计算', '理解', '信息提取', '推理', '空间', '记忆'] as const

  const difficultyLabels: Record<number, { label: string; color: string }> = {
    1: { label: '★', color: '#52c41a' },
    2: { label: '★★', color: '#73d13d' },
    3: { label: '★★★', color: '#faad14' },
    4: { label: '★★★★', color: '#fa8c16' },
    5: { label: '★★★★★', color: '#f5222d' },
  }

  const paperColumns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 50 },
    { title: '试卷标题', dataIndex: 'title', key: 'title', width: 200, ellipsis: true },
    { title: '文件名', dataIndex: 'original_filename', key: 'original_filename', width: 220, ellipsis: true, render: (v: string) => v || '-' },
    {
      title: '类型', dataIndex: 'paper_type', key: 'paper_type', width: 80,
      render: (v: string) => v === 'real' ? <Tag color="red">真题</Tag> : <Tag color="blue">模拟题</Tag>
    },
    { title: '年级', dataIndex: 'grade', key: 'grade', width: 80 },
    { title: '年份', dataIndex: 'year', key: 'year', width: 70 },
    { title: '题目数', dataIndex: 'total_questions', key: 'total_questions', width: 70 },
    {
      title: '挂载', key: 'link_stat', width: 110,
      render: (_: any, record: any) => {
        const total = record.total_questions || 0
        const linked = record.linked_count || 0
        if (!total) return '-'
        const rate = Math.round((linked / total) * 100)
        const color = rate >= 90 ? undefined : '#faad14'
        return <span style={{ color }}>{linked}/{total}（{rate}%）</span>
      }
    },
    {
      title: '解析状态', dataIndex: 'parse_status', key: 'parse_status', width: 100,
      render: (v: string) => {
        const info = parseStatusLabels[v] || { label: v, color: 'default' }
        return <Tag color={info.color}>{info.label}</Tag>
      }
    },
    {
      title: '操作', key: 'action', width: 260,
      render: (_: any, record: any) => (
        <Space size="small" wrap>
          <Tooltip title="打开本卷结构模板；缺分值可在明细中补填并写回题目">
            <Button
              type="link"
              size="small"
              icon={<ProfileOutlined />}
              loading={buildLoadingId === record.id}
              onClick={() => handleBuildTemplate(record.id)}
            >
              本卷模板
            </Button>
          </Tooltip>
          <Tooltip title="编辑试卷信息">
            <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEditPaper(record)} />
          </Tooltip>
          <Tooltip title="重新解析">
            <Button type="link" size="small" icon={<ReloadOutlined />} onClick={() => handleReparsePaper(record.id)} />
          </Tooltip>
          <Popconfirm title="确认删除试卷及所有题目？" onConfirm={() => handleDeletePaper(record.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      )
    },
  ]

  const questionColumns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 50 },
    { title: '序号', dataIndex: 'question_number', key: 'question_number', width: 60 },
    {
      title: '题目类型', dataIndex: 'question_type', key: 'question_type', width: 90,
      render: (v: string) => {
        const info = questionTypeLabels[v] || { label: v, color: 'default' }
        return <Tag color={info.color}>{info.label}</Tag>
      }
    },
    {
      title: '分值', dataIndex: 'score', key: 'score', width: 70,
      render: (v: number | null | undefined) =>
        v != null ? v : <span style={{ color: '#ff4d4f' }}>-</span>,
    },
    {
      title: '题目内容', dataIndex: 'content', key: 'content', ellipsis: false,
      render: (v: string, record: any) => {
        // 拼接选项到展示内容
        let display = v || ''
        if (record.options && typeof record.options === 'object') {
          const optStr = Object.entries(record.options)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([k, val]) => `${k}. ${val}`)
            .join('  ')
          if (optStr) display = display + '\n' + optStr
        }
        // 智能截断：避免从[IMG:...]占位符中间截断
        let shortDisplay = display
        if (display.length > 120) {
          let cutPos = 120
          // 往回找最近的[IMG:，检查是否还没闭合
          const before = display.substring(0, cutPos)
          const lastOpen = before.lastIndexOf('[IMG:')
          if (lastOpen >= 0) {
            const closeBracket = display.indexOf(']', lastOpen)
            if (closeBracket >= cutPos) {
              // [IMG:...]跨越了截断点，扩展到]之后
              cutPos = closeBracket + 1
            }
          }
          shortDisplay = display.substring(0, cutPos) + '...'
        }
        return (
          <Tooltip title={renderRichContentTooltip(display, record.exam_paper_id)} overlayStyle={{ maxWidth: 520 }} color="white" overlayInnerStyle={{ color: '#333' }}>
            <div style={{ maxHeight: 56, overflow: 'hidden', cursor: 'pointer' }}>
              {renderRichContent(shortDisplay, record.exam_paper_id)}
            </div>
          </Tooltip>
        )
      }
    },
    {
      title: '答案', dataIndex: 'answer', key: 'answer', width: 120, ellipsis: true,
      render: (v: string, record: any) => {
        if (!v) return '-'
        const laid = formatAnswerLayout(v)
        let short = laid
        if (laid.length > 36) {
          let cutPos = 36
          const before = laid.substring(0, cutPos)
          const lastOpen = before.lastIndexOf('[IMG:')
          if (lastOpen >= 0) {
            const close = laid.indexOf(']', lastOpen)
            if (close >= cutPos) cutPos = close + 1
          }
          short = laid.substring(0, cutPos) + '...'
        }
        return (
          <Tooltip
            title={renderRichContentTooltip(v, record.exam_paper_id, { answerLayout: true })}
            overlayStyle={{ maxWidth: 520 }}
            color="white"
            overlayInnerStyle={{ color: '#333', padding: '10px 14px' }}
          >
            <div style={{ maxHeight: 44, overflow: 'hidden', cursor: 'pointer', fontSize: 14 }}>
              {renderRichContent(short, record.exam_paper_id, { answerLayout: true })}
            </div>
          </Tooltip>
        )
      }
    },
    {
      title: '解析', dataIndex: 'analysis', key: 'analysis', width: 150, ellipsis: true,
      render: (v: string, record: any) => {
        if (!v) return '-'
        let short = v
        if (v.length > 40) {
          let cutPos = 40
          const before = v.substring(0, cutPos)
          const lastOpen = before.lastIndexOf('[IMG:')
          if (lastOpen >= 0) {
            const close = v.indexOf(']', lastOpen)
            if (close >= cutPos) cutPos = close + 1
          }
          short = v.substring(0, cutPos) + '...'
        }
        return (
          <Tooltip title={renderRichContentTooltip(v, record.exam_paper_id)} overlayStyle={{ maxWidth: 520 }} color="white" overlayInnerStyle={{ color: '#333' }}>
            <div style={{ maxHeight: 40, overflow: 'hidden', cursor: 'pointer' }}>
              {renderRichContent(short, record.exam_paper_id)}
            </div>
          </Tooltip>
        )
      }
    },
    {
      title: '难度', dataIndex: 'difficulty', key: 'difficulty', width: 100,
      render: (v: number) => {
        const info = difficultyLabels[v] || { label: `${v}`, color: '#666' }
        return <span style={{ color: info.color }}>{info.label}</span>
      }
    },
    {
      title: '能力维度', dataIndex: 'ability_dimension', key: 'ability_dimension', width: 100,
      render: (v: string) => v ? <Tag>{v}</Tag> : <span style={{ color: '#999' }}>-</span>,
    },
    {
      title: '关联置信度', dataIndex: 'primary_kp_confidence', key: 'primary_kp_confidence', width: 110,
      render: (v: string) => {
        if (!v) return <span style={{ color: '#999' }}>-</span>
        const map: Record<string, { label: string; color: string }> = {
          high: { label: '高', color: 'green' },
          medium: { label: '中', color: 'orange' },
          low: { label: '低', color: 'default' },
          manual: { label: '人工', color: 'blue' },
        }
        const info = map[v] || { label: v, color: 'default' }
        return <Tag color={info.color}>{info.label}</Tag>
      }
    },
    {
      title: '主知识点', dataIndex: 'primary_kp_name', key: 'primary_kp_name', width: 200, ellipsis: true,
      render: (v: string, record: any) => {
        if (v) {
          const tipContent = (
            <div style={{ fontSize: 13, lineHeight: 1.8 }}>
              <div><b>ID：</b>{record.primary_kp_id}</div>
              <div><b>描述：</b>{v}</div>
              <div><b>一级分类：</b>{record.primary_kp_category_1 || '-'}</div>
              <div><b>二级分类：</b>{record.primary_kp_category_2 || '-'}</div>
            </div>
          )
          return (
            <Tooltip title={tipContent} overlayStyle={{ maxWidth: 480 }} color="white" overlayInnerStyle={{ color: '#333' }}>
              <span style={{ cursor: 'pointer' }}>
                {v}
                {record.has_pending_suggestion && <Tag color="orange" style={{ marginLeft: 4 }}>待确认</Tag>}
              </span>
            </Tooltip>
          )
        }
        return (
          <span>
            <Tag color="error">未挂载</Tag>
            {record.has_pending_suggestion && <Tag color="orange">待确认</Tag>}
          </span>
        )
      }
    },
    {
      title: '操作', key: 'action', width: 120,
      render: (_: any, record: any) => (
        <Space size="small">
          <Tooltip title="查看">
            <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => { setDetailQuestion(record); setDetailVisible(true) }} />
          </Tooltip>
          <Tooltip title="编辑">
            <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEditQuestion(record)} />
          </Tooltip>
          <Popconfirm title="确认删除？" onConfirm={() => handleDeleteQuestion(record.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      )
    },
  ]

  const filteredPapers = papers.filter(p => p.paper_type === filterBankType)

  const renderQuestionsPanel = () => (
    <div>
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Tag color={linkRate >= 90 ? 'success' : 'warning'}>
            挂载 {linkedCount} 题 · {linkRate}%
          </Tag>
          <Select
            placeholder="按试卷筛选"
            allowClear
            style={{ width: 200 }}
            value={filterPaperId}
            onChange={v => setFilterPaperId(v)}
          >
            {filteredPapers.map(p => (
              <Option key={p.id} value={p.id}>{p.title}</Option>
            ))}
          </Select>
          <Select
            placeholder="挂载状态"
            allowClear
            style={{ width: 120 }}
            value={filterLinkStatus}
            onChange={v => setFilterLinkStatus(v)}
          >
            <Option value="linked">已挂载</Option>
            <Option value="unlinked">未挂载</Option>
            <Option value="pending">待确认</Option>
          </Select>
          <Select
            placeholder="题目类型"
            allowClear
            style={{ width: 120 }}
            value={filterType}
            onChange={v => setFilterType(v)}
          >
            <Option value="choice">选择题</Option>
            <Option value="fill">填空题</Option>
            <Option value="answer">解答题</Option>
            <Option value="proof">证明题</Option>
          </Select>
          <Select
            placeholder="难度"
            allowClear
            style={{ width: 100 }}
            value={filterDifficulty}
            onChange={v => setFilterDifficulty(v)}
          >
            <Option value={1}>★</Option>
            <Option value={2}>★★</Option>
            <Option value={3}>★★★</Option>
            <Option value={4}>★★★★</Option>
            <Option value={5}>★★★★★</Option>
          </Select>
          <Select
            placeholder="能力维度"
            allowClear
            style={{ width: 120 }}
            value={filterAbilityDimension}
            onChange={v => setFilterAbilityDimension(v)}
          >
            {abilityDimensionOptions.map(d => (
              <Option key={d} value={d}>{d}</Option>
            ))}
          </Select>
          <Input.Search
            placeholder="搜索题目内容"
            allowClear
            style={{ width: 200 }}
            onSearch={v => setFilterKeyword(v || undefined)}
          />
          <Button icon={<ReloadOutlined />} onClick={() => fetchQuestions()}>刷新</Button>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            onClick={() => {
              setLinkScope(selectedRowKeys.length > 0 ? 'selected' : (filterPaperId ? 'paper' : 'unlinked'))
              setLinkModalVisible(true)
            }}
          >
            批量智能关联
          </Button>
          <Button
            icon={<ThunderboltOutlined />}
            onClick={() => {
              setAbilityScope(
                selectedRowKeys.length > 0 ? 'selected' : (filterPaperId ? 'paper' : 'unlabeled'),
              )
              setAbilityModalVisible(true)
            }}
          >
            AI标注能力维度
          </Button>
          <Button
            icon={<FontSizeOutlined />}
            loading={rewriteImgLoading}
            onClick={handleBatchRewriteImageAnswers}
          >
            图片答案转文本
          </Button>
          <Dropdown
            menu={{
              items: [
                {
                  key: 'kp',
                  label: '知识点关联',
                  onClick: () => openConfirmDrawer(linkTaskId || undefined),
                },
                {
                  key: 'ability',
                  label: '能力维度',
                  onClick: () => openAbilityDrawer(abilityTaskId || undefined),
                },
                {
                  key: 'answer',
                  label: '答案转写',
                  onClick: () => openAnswerRewriteDrawer(answerRewriteTaskId || undefined),
                },
              ],
            }}
          >
            <Button>
              待确认结果 <DownOutlined />
            </Button>
          </Dropdown>
        </Space>
        {selectedRowKeys.length > 0 && (
          <Space wrap style={{ marginTop: 12 }}>
            <span>已选 {selectedRowKeys.length} 题</span>
            <Popconfirm
              title={`确认删除选中的 ${selectedRowKeys.length} 道题？`}
              description="删除后不可恢复"
              okText="删除"
              okButtonProps={{ danger: true }}
              cancelText="取消"
              onConfirm={handleBatchDeleteQuestions}
            >
              <Button danger icon={<DeleteOutlined />}>
                批量删除选中
              </Button>
            </Popconfirm>
            <span>，批量指定主知识点：</span>
            <Select
              showSearch
              allowClear
              placeholder="搜索知识点名称"
              style={{ width: 280 }}
              options={kpOptions}
              value={batchKpId}
              onChange={setBatchKpId}
              filterOption={false}
              onSearch={v => searchKnowledgePoints(v)}
              loading={kpSearching}
            />
            <Button type="primary" onClick={handleBatchSetPrimaryKp}>应用</Button>
          </Space>
        )}
        {linkTaskId && (linkTaskStatus === 'running' || linkTaskStatus === 'pending') && (
          <div style={{ marginTop: 12 }}>
            <Text type="secondary">智能关联任务 #{linkTaskId}</Text>
            <Progress percent={linkTaskProgress} size="small" status="active" />
          </div>
        )}
        {answerRewriteTaskId && (answerRewriteStatus === 'running' || answerRewriteStatus === 'pending') && (
          <div style={{ marginTop: 12 }}>
            <Text type="secondary">答案转写任务 #{answerRewriteTaskId}</Text>
            <Progress percent={answerRewriteProgress} size="small" status="active" />
          </div>
        )}
        {abilityTaskId && (abilityTaskStatus === 'running' || abilityTaskStatus === 'pending') && (
          <div style={{ marginTop: 12 }}>
            <Text type="secondary">能力维度标注任务 #{abilityTaskId}</Text>
            <Progress percent={abilityTaskProgress} size="small" status="active" />
          </div>
        )}
      </Card>
      <Table
        columns={questionColumns}
        dataSource={questions}
        rowKey="id"
        loading={questionsLoading}
        size="small"
        rowSelection={{
          selectedRowKeys,
          onChange: setSelectedRowKeys,
        }}
        pagination={{
          current: currentPage,
          pageSize,
          total: totalQuestions,
          showTotal: t => `共 ${t} 题`,
          onChange: (page) => { setCurrentPage(page); fetchQuestions(page) },
        }}
        scroll={{ x: 1100 }}
      />
    </div>
  )

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          {activeTab === 'papers' ? '试卷管理' : activeTab === 'real-questions' ? '真题题库' : activeTab === 'ai-questions' ? 'AI题库' : '模拟题库'}
        </Title>
        <Space>
          {activeTab === 'real-questions' && (
            <Popconfirm
              title="确认清除全部真题？"
              description="将删除所有真题试卷、题目及关联图片，不影响模拟题。"
              onConfirm={() => handleClearByType('real')}
              okText="确认清除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
            >
              <Button danger icon={<DeleteOutlined />}>一键清除真题</Button>
            </Popconfirm>
          )}
          {activeTab === 'mock-questions' && (
            <Popconfirm
              title="确认清除全部模拟题？"
              description="将删除所有模拟试卷、题目及关联图片，不影响真题。"
              onConfirm={() => handleClearByType('mock')}
              okText="确认清除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
            >
              <Button danger icon={<DeleteOutlined />}>一键清除模拟题</Button>
            </Popconfirm>
          )}
          {activeTab !== 'ai-questions' && (
            <Button type="primary" icon={<UploadOutlined />} onClick={() => setUploadModalVisible(true)}>
              上传试卷
            </Button>
          )}
        </Space>
      </div>

      {activeTab === 'papers' && (
        <div>
          <Card size="small" style={{ marginBottom: 16, background: '#f6ffed', border: '1px solid #b7eb8f' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
              <p style={{ margin: 0 }}>
                <strong>使用说明：</strong>题目分值来自原文件识别或手工填写。「本卷模板」缺分也可打开，在题目明细里补分会写回该卷题目并刷新统计；多套勾选后可生成/查看等权平均模板。
              </p>
              <Space>
                <Button
                  type="primary"
                  icon={<ProfileOutlined />}
                  loading={buildSelectedLoading}
                  disabled={!selectedPaperKeys.length}
                  onClick={handleBuildFromSelected}
                >
                  从所选试卷生成模板{selectedPaperKeys.length ? `（${selectedPaperKeys.length}）` : ''}
                </Button>
                <Button
                  icon={<UnorderedListOutlined />}
                  loading={viewAverageLoading}
                  onClick={handleViewAverageTemplate}
                >
                  查看平均模板{selectedPaperKeys.length >= 2 ? `（${selectedPaperKeys.length}）` : ''}
                </Button>
              </Space>
            </div>
          </Card>
          <Table
            columns={paperColumns}
            dataSource={papers}
            rowKey="id"
            loading={papersLoading}
            size="small"
            pagination={false}
            scroll={{ x: 1400 }}
            rowSelection={{
              selectedRowKeys: selectedPaperKeys,
              onChange: setSelectedPaperKeys,
            }}
          />
        </div>
      )}
      {(activeTab === 'real-questions' || activeTab === 'mock-questions' || activeTab === 'ai-questions') && renderQuestionsPanel()}

      {/* 编辑试卷弹窗 */}
      <Modal
        title={`编辑试卷 #${editingPaper?.id || ''}`}
        open={editPaperModalVisible}
        onOk={handleEditPaper}
        onCancel={() => {
          setEditPaperModalVisible(false)
          setEditingPaper(null)
          editPaperForm.resetFields()
        }}
        okText="保存"
        confirmLoading={editPaperSaving}
        destroyOnClose
        width={480}
      >
        <Form form={editPaperForm} layout="vertical">
          <Form.Item name="title" label="试卷标题" rules={[{ required: true, message: '请输入试卷标题' }]}>
            <Input placeholder="试卷标题" />
          </Form.Item>
          <Form.Item name="paper_type" label="试卷类型" rules={[{ required: true }]}>
            <Select>
              <Option value="real">真题</Option>
              <Option value="mock">模拟题</Option>
            </Select>
          </Form.Item>
          <Space style={{ width: '100%' }} size={16} wrap>
            <Form.Item name="grade" label="年级" style={{ marginBottom: 0 }}>
              <Select placeholder="年级" allowClear style={{ width: 120 }}>
                <Option value="七年级">七年级</Option>
                <Option value="八年级">八年级</Option>
                <Option value="九年级">九年级</Option>
              </Select>
            </Form.Item>
            <Form.Item name="year" label="年份" style={{ marginBottom: 0 }}>
              <Input placeholder="2025" style={{ width: 100 }} />
            </Form.Item>
            <Form.Item name="region" label="地区" style={{ marginBottom: 0 }}>
              <Input placeholder="浙江" style={{ width: 100 }} />
            </Form.Item>
          </Space>
        </Form>
      </Modal>

      {/* 上传试卷弹窗 */}
      <Modal
        title="上传试卷"
        open={uploadModalVisible}
        onOk={handleUpload}
        onCancel={() => { setUploadModalVisible(false); uploadForm.resetFields(); setUploadFile(null) }}
        okText="上传并解析"
        confirmLoading={uploading}
        destroyOnClose
        width={500}
      >
        <Form form={uploadForm} layout="vertical">
          <Form.Item name="title" label="试卷标题" rules={[{ required: true, message: '请输入试卷标题' }]}>
            <Input placeholder="如：2024年北京市中考数学真题" />
          </Form.Item>
          <Form.Item name="paper_type" label="试卷类型" initialValue="real">
            <Select>
              <Option value="real">真题</Option>
              <Option value="mock">模拟题</Option>
            </Select>
          </Form.Item>
          <Form.Item label="试卷文件" required>
            <Upload
              beforeUpload={(file) => { setUploadFile(file); return false }}
              onRemove={() => setUploadFile(null)}
              fileList={uploadFile ? [uploadFile] : []}
              accept=".docx,.doc"
              maxCount={1}
            >
              <Button icon={<FileWordOutlined />}>选择Word文件</Button>
            </Upload>
          </Form.Item>
          <Space style={{ width: '100%' }} size={16}>
            <Form.Item name="grade" label="年级" style={{ marginBottom: 0 }}>
              <Select placeholder="年级" allowClear style={{ width: 120 }}>
                <Option value="七年级">七年级</Option>
                <Option value="八年级">八年级</Option>
                <Option value="九年级">九年级</Option>
              </Select>
            </Form.Item>
            <Form.Item name="year" label="年份" style={{ marginBottom: 0 }}>
              <Input placeholder="2024" style={{ width: 100 }} />
            </Form.Item>
            <Form.Item name="region" label="地区" style={{ marginBottom: 0 }}>
              <Input placeholder="北京" style={{ width: 100 }} />
            </Form.Item>
          </Space>
        </Form>
      </Modal>

      {/* 编辑题目抽屉 */}
      <Drawer
        title={`编辑题目 #${editingQuestion?.id || ''}`}
        open={editDrawerVisible}
        onClose={() => setEditDrawerVisible(false)}
        width={600}
        extra={
          <Button type="primary" onClick={handleSaveQuestion}>保存</Button>
        }
      >
        <Form form={editForm} layout="vertical">
          <Space style={{ width: '100%' }} size={16}>
            <Form.Item name="question_type" label="题目类型" rules={[{ required: true }]}>
              <Select style={{ width: 120 }}>
                <Option value="choice">选择题</Option>
                <Option value="fill">填空题</Option>
                <Option value="answer">解答题</Option>
                <Option value="proof">证明题</Option>
              </Select>
            </Form.Item>
            <Form.Item name="question_number" label="题号">
              <InputNumber min={1} />
            </Form.Item>
            <Form.Item name="difficulty" label="难度">
              <Select style={{ width: 100 }}>
                <Option value={1}>★</Option>
                <Option value={2}>★★</Option>
                <Option value={3}>★★★</Option>
                <Option value={4}>★★★★</Option>
                <Option value={5}>★★★★★</Option>
              </Select>
            </Form.Item>
          </Space>
          <Form.Item name="content" label="题目内容" rules={[{ required: true }]}>
            <TextArea rows={6} />
          </Form.Item>
          <Form.Item
            name="answer"
            label="答案"
            tooltip="支持公式编辑与预览；根号横线在预览/公式模式中显示"
          >
            <AnswerFormulaInput rows={3} />
          </Form.Item>
          <Form.Item name="analysis" label="解析">
            <TextArea rows={3} />
          </Form.Item>
          <Form.Item name="score" label="分值">
            <InputNumber min={0} step={0.5} />
          </Form.Item>
          <Form.Item name="ability_dimension" label="能力维度">
            <Select allowClear placeholder="选择能力维度">
              {abilityDimensionOptions.map(d => (
                <Option key={d} value={d}>{d}</Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="primary_kp_id" label="主知识点">
            <Select
              showSearch
              allowClear
              placeholder="搜索知识点名称"
              options={kpOptions}
              filterOption={false}
              onSearch={v => searchKnowledgePoints(v)}
              loading={kpSearching}
              notFoundContent={kpSearching ? '搜索中...' : '无匹配知识点'}
            />
          </Form.Item>
        </Form>
      </Drawer>

      {/* 查看题目详情 */}
      <Modal
        title={`题目详情 #${detailQuestion?.id || ''}`}
        open={detailVisible}
        onCancel={() => setDetailVisible(false)}
        footer={null}
        width={700}
      >
        {detailQuestion && (
          <div>
            <p><strong>题号：</strong>{detailQuestion.question_number || '-'}</p>
            <p><strong>类型：</strong>{questionTypeLabels[detailQuestion.question_type]?.label || detailQuestion.question_type}</p>
            <p><strong>难度：</strong>{difficultyLabels[detailQuestion.difficulty]?.label || detailQuestion.difficulty}</p>
            <p><strong>题目内容：</strong></p>
            <Card size="small" style={{ marginBottom: 12 }}>
              {renderRichContentLarge(detailQuestion.content, detailQuestion.exam_paper_id)}
            </Card>
            {detailQuestion.options && (
              <div style={{ marginBottom: 12 }}>
                <strong>选项：</strong>
                <ul style={{ margin: '4px 0', paddingLeft: 20 }}>
                  {Object.entries(detailQuestion.options).map(([k, v]) => (
                    <li key={k}>{k}. {renderRichContent(v as string, detailQuestion.exam_paper_id)}</li>
                  ))}
                </ul>
              </div>
            )}
            <p><strong>答案：</strong>{renderRichContent(detailQuestion.answer || '未填写', detailQuestion.exam_paper_id, { answerLayout: true })}</p>
            <p><strong>解析：</strong></p>
            <Card size="small" style={{ marginBottom: 12 }}>
              {renderRichContentLarge(detailQuestion.analysis || '未填写', detailQuestion.exam_paper_id)}
            </Card>
            <p><strong>分值：</strong>{detailQuestion.score || '-'}</p>
            <p><strong>能力维度：</strong>{detailQuestion.ability_dimension || '-'}</p>
            <p>
              <strong>主知识点：</strong>
              {detailQuestion.primary_kp_name
                ? `${detailQuestion.primary_kp_name}（${detailQuestion.primary_kp_id}）`
                : <Tag color="error">未挂载</Tag>}
            </p>
            <p>
              <strong>关联置信度：</strong>
              {detailQuestion.primary_kp_confidence
                ? ({ high: '高', medium: '中', low: '低', manual: '人工' } as Record<string, string>)[
                    detailQuestion.primary_kp_confidence
                  ] || detailQuestion.primary_kp_confidence
                : '-'}
            </p>
          </div>
        )}
      </Modal>

      {/* 批量智能关联 */}
      <Modal
        title="批量智能关联主知识点"
        open={linkModalVisible}
        onOk={handleStartKpLink}
        onCancel={() => setLinkModalVisible(false)}
        okText="开始关联"
        confirmLoading={linkStarting}
        destroyOnClose
      >
        <p style={{ marginBottom: 12, color: '#666' }}>
          大模型仅生成建议，需人工确认后才会写入主知识点。
        </p>
        <Radio.Group
          value={linkScope}
          onChange={e => setLinkScope(e.target.value)}
          style={{ display: 'flex', flexDirection: 'column', gap: 10 }}
        >
          <Radio value="unlinked">
            当前筛选范围内未挂载题目
            {filterPaperId ? '（含所选试卷）' : '（全部未挂载）'}
          </Radio>
          <Radio value="paper" disabled={!filterPaperId}>
            当前试卷全部未挂载题{filterPaperId ? '' : '（请先筛选试卷）'}
          </Radio>
          <Radio value="selected" disabled={selectedRowKeys.length === 0}>
            已勾选的 {selectedRowKeys.length} 题
          </Radio>
        </Radio.Group>
      </Modal>

      {/* AI 标注能力维度 */}
      <Modal
        title="AI 批量标注能力维度"
        open={abilityModalVisible}
        onOk={handleStartAbilityLabel}
        onCancel={() => setAbilityModalVisible(false)}
        okText="开始标注"
        confirmLoading={abilityStarting}
        destroyOnClose
      >
        <p style={{ marginBottom: 12, color: '#666' }}>
          AI将自动为题目标注能力维度（计算 / 理解 / 信息提取 / 推理 / 空间 / 记忆），结果直接写入，已有标注将被覆盖。
        </p>
        <Radio.Group
          value={abilityScope}
          onChange={e => setAbilityScope(e.target.value)}
          style={{ display: 'flex', flexDirection: 'column', gap: 10 }}
        >
          <Radio value="unlabeled">
            仅标注未标注的题目
            {filterPaperId ? '（当前试卷范围）' : ''}
          </Radio>
          <Radio value="paper" disabled={!filterPaperId}>
            当前试卷全部题目（覆盖已有标注）{filterPaperId ? '' : '（请先筛选试卷）'}
          </Radio>
          <Radio value="selected" disabled={selectedRowKeys.length === 0}>
            已勾选的 {selectedRowKeys.length} 道题（覆盖已有标注）
          </Radio>
        </Radio.Group>
      </Modal>

      {/* 确认能力维度标注 */}
      <Drawer
        title="确认能力维度标注"
        open={abilityDrawerVisible}
        onClose={() => setAbilityDrawerVisible(false)}
        width={900}
        extra={
          <Space>
            <Button onClick={handleAcceptAllAbilityHigh}>全部采用高置信</Button>
            <Button type="primary" loading={abilitySaving} onClick={handleConfirmAbilityLabel}>
              保存确认
            </Button>
          </Space>
        }
      >
        <p style={{ marginBottom: 12, color: '#666' }}>
          以下为模型建议，采用/改选后才会写入列表中的能力维度。
        </p>
        <Table
          size="small"
          rowKey="id"
          dataSource={abilitySuggestions}
          pagination={{ pageSize: 20 }}
          columns={[
            {
              title: '题号',
              dataIndex: 'question_number',
              width: 56,
              render: (v: number) => v ?? '-',
            },
            {
              title: '题干摘要',
              dataIndex: 'question_content',
              width: 220,
              ellipsis: true,
              render: (v: string) => v || '-',
            },
            {
              title: '当前',
              dataIndex: 'current_dimension',
              width: 80,
              render: (v: string) => v || <span style={{ color: '#999' }}>-</span>,
            },
            {
              title: '建议维度',
              dataIndex: 'suggested_dimension',
              width: 160,
              render: (v: string, record: any) => (
                <div>
                  {v ? <Tag color="blue">{v}</Tag> : <Tag color="error">无建议</Tag>}
                  {record.reason && (
                    <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>{record.reason}</div>
                  )}
                </div>
              ),
            },
            {
              title: '置信度',
              dataIndex: 'confidence',
              width: 72,
              render: (v: string) => {
                const color = v === 'high' ? 'green' : v === 'medium' ? 'orange' : 'default'
                return <Tag color={color}>{v || '-'}</Tag>
              },
            },
            {
              title: '操作',
              key: 'ops',
              width: 240,
              render: (_: any, record: any) => {
                const edit = abilityEdits[record.id] || { action: 'reject' }
                return (
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    <Radio.Group
                      size="small"
                      value={edit.action}
                      onChange={e => {
                        const action = e.target.value
                        setAbilityEdits(prev => ({
                          ...prev,
                          [record.id]: {
                            action,
                            ability_dimension:
                              action === 'accept'
                                ? record.suggested_dimension
                                : prev[record.id]?.ability_dimension,
                          },
                        }))
                      }}
                    >
                      <Radio.Button value="accept" disabled={!record.suggested_dimension}>采用</Radio.Button>
                      <Radio.Button value="modify">改选</Radio.Button>
                      <Radio.Button value="reject">拒绝</Radio.Button>
                    </Radio.Group>
                    {edit.action === 'modify' && (
                      <Select
                        size="small"
                        placeholder="改选能力维度"
                        style={{ width: '100%' }}
                        value={edit.ability_dimension}
                        onChange={v => setAbilityEdits(prev => ({
                          ...prev,
                          [record.id]: { action: 'modify', ability_dimension: v },
                        }))}
                        options={abilityDimensionOptions.map(d => ({ value: d, label: d }))}
                      />
                    )}
                  </Space>
                )
              },
            },
          ]}
        />
      </Drawer>

      {/* 确认答案转写结果 */}
      <Drawer
        title="确认答案转写结果"
        open={answerRewriteDrawerVisible}
        onClose={() => setAnswerRewriteDrawerVisible(false)}
        width={920}
        extra={
          <Space>
            <Button onClick={handleAcceptAllAnswerRewrite}>全部采用</Button>
            <Button type="primary" loading={answerRewriteSaving} onClick={handleConfirmAnswerRewrite}>
              保存确认
            </Button>
          </Space>
        }
      >
        <p style={{ marginBottom: 12, color: '#666' }}>
          以下为识别建议，采用后才会改写列表中的答案；拒绝则保留原答案。
        </p>
        <Table
          size="small"
          rowKey="id"
          dataSource={answerRewriteSuggestions}
          pagination={{ pageSize: 10 }}
          columns={[
            {
              title: '题号',
              dataIndex: 'question_number',
              width: 56,
              render: (v: number) => v ?? '-',
            },
            {
              title: '原答案',
              dataIndex: 'original_answer',
              width: 280,
              render: (v: string, record: any) => (
                <div style={{ maxHeight: 120, overflow: 'auto', fontSize: 13, lineHeight: 1.6 }}>
                  {renderRichContent(v || '-', record.exam_paper_id)}
                </div>
              ),
            },
            {
              title: '转写后',
              dataIndex: 'suggested_answer',
              width: 280,
              render: (v: string, record: any) => (
                <div style={{ maxHeight: 120, overflow: 'auto', fontSize: 13, lineHeight: 1.6 }}>
                  {renderRichContent(v || '-', record.exam_paper_id, { answerLayout: true })}
                </div>
              ),
            },
            {
              title: '置信度',
              dataIndex: 'confidence',
              width: 72,
              render: (v: string) => {
                const color = v === 'high' ? 'green' : v === 'medium' ? 'orange' : 'default'
                return <Tag color={color}>{v || '-'}</Tag>
              },
            },
            {
              title: '操作',
              key: 'ops',
              width: 140,
              render: (_: any, record: any) => {
                const action = answerRewriteEdits[record.id] || 'reject'
                return (
                  <Radio.Group
                    size="small"
                    value={action}
                    onChange={e => setAnswerRewriteEdits(prev => ({
                      ...prev,
                      [record.id]: e.target.value,
                    }))}
                  >
                    <Radio.Button value="accept" disabled={!record.suggested_answer}>采用</Radio.Button>
                    <Radio.Button value="reject">拒绝</Radio.Button>
                  </Radio.Group>
                )
              },
            },
          ]}
        />
      </Drawer>

      {/* 确认智能关联结果 */}
      <Drawer
        title="确认智能关联结果"
        open={confirmDrawerVisible}
        onClose={() => setConfirmDrawerVisible(false)}
        width={860}
        extra={
          <Space>
            <Button onClick={handleAcceptAllHigh}>全部采用高置信</Button>
            <Button type="primary" loading={confirmSaving} onClick={handleConfirmSuggestions}>
              保存确认
            </Button>
          </Space>
        }
      >
        <Table
          size="small"
          rowKey="id"
          dataSource={suggestions}
          pagination={{ pageSize: 20 }}
          columns={[
            {
              title: '题号',
              dataIndex: 'question_number',
              width: 60,
              render: (v: number) => v ?? '-',
            },
            {
              title: '题干摘要',
              dataIndex: 'question_content',
              width: 220,
              ellipsis: true,
              render: (v: string) => v || '-',
            },
            {
              title: '建议主知识点',
              dataIndex: 'suggested_kp_name',
              width: 160,
              render: (v: string, record: any) => (
                <div>
                  {v ? v : <Tag color="error">无建议</Tag>}
                  {record.reason && (
                    <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>{record.reason}</div>
                  )}
                </div>
              ),
            },
            {
              title: '置信度',
              dataIndex: 'confidence',
              width: 80,
              render: (v: string) => {
                const color = v === 'high' ? 'green' : v === 'medium' ? 'orange' : 'default'
                return <Tag color={color}>{v || '-'}</Tag>
              },
            },
            {
              title: '操作',
              key: 'ops',
              width: 260,
              render: (_: any, record: any) => {
                const edit = suggestionEdits[record.id] || { action: 'reject' }
                return (
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    <Radio.Group
                      size="small"
                      value={edit.action}
                      onChange={e => {
                        const action = e.target.value
                        setSuggestionEdits(prev => ({
                          ...prev,
                          [record.id]: {
                            action,
                            kp_id: action === 'accept' ? record.suggested_kp_id : prev[record.id]?.kp_id,
                          },
                        }))
                      }}
                    >
                      <Radio.Button value="accept" disabled={!record.suggested_kp_id}>采用</Radio.Button>
                      <Radio.Button value="modify">改选</Radio.Button>
                      <Radio.Button value="reject">拒绝</Radio.Button>
                    </Radio.Group>
                    {edit.action === 'modify' && (
                      <Select
                        showSearch
                        size="small"
                        placeholder="改选知识点"
                        style={{ width: '100%' }}
                        options={kpOptions}
                        value={edit.kp_id}
                        filterOption={false}
                        onSearch={v => searchKnowledgePoints(v)}
                        onChange={v => setSuggestionEdits(prev => ({
                          ...prev,
                          [record.id]: { action: 'modify', kp_id: v },
                        }))}
                      />
                    )}
                  </Space>
                )
              },
            },
          ]}
        />
      </Drawer>

      {/* 模板详情 */}
      <Drawer
        title={templateDetail?.name || '结构模板'}
        open={templateDrawerVisible}
        onClose={() => setTemplateDrawerVisible(false)}
        width={880}
        extra={
          templateDetail && (
            <Space>
              {templateDetail.is_default ? (
                <Button onClick={() => handleUnsetDefaultTemplate(templateDetail.id)}>取消默认</Button>
              ) : (
                <Button
                  type="primary"
                  disabled={templateDetail.status !== 'ready'}
                  onClick={() => handleSetDefaultTemplate(templateDetail.id)}
                >
                  设为默认
                </Button>
              )}
            </Space>
          )
        }
      >
        {templateDetail && (
          <div>
            <Space wrap style={{ marginBottom: 16 }}>
              <Tag color={templateDetail.status === 'ready' ? 'blue' : 'orange'}>
                {templateDetail.status === 'ready' ? 'ready' : 'incomplete'}
              </Tag>
              {templateDetail.is_default && <Tag color="green">默认模板</Tag>}
              {templateDetail.used_temp_scores && <Tag color="gold">统计含临时分值</Tag>}
              <Text>总分 {templateDetail.total_score}</Text>
              <Text type="secondary">
                来源 {templateDetail.source_paper_ids?.length || 0} 套卷
                {templateDetail.source_paper_ids?.length
                  ? `（ID: ${(templateDetail.source_paper_ids || []).join(', ')}）`
                  : ''}
              </Text>
            </Space>
            {(templateDetail.build_meta?.missing_score_count > 0) && (
              <Card size="small" style={{ marginBottom: 12, borderColor: '#ffe58f', background: '#fffbe6' }}>
                <Text>
                  尚有 {templateDetail.build_meta.missing_score_count} 题缺分值（题量仍计入，小计/占比不含缺分题）。
                  {(templateDetail.source_paper_ids?.length || 0) <= 1
                    ? '请在下方「题目明细」中填写，将自动写回题目并刷新本模板。'
                    : '请回到各卷「本卷模板」补分后再生成平均模板。'}
                </Text>
              </Card>
            )}
            {templateDetail.build_meta?.unlinked_count > 0 && (
              <Card size="small" style={{ marginBottom: 12, borderColor: '#ffccc7' }}>
                <Text type="danger">
                  未挂载 {templateDetail.build_meta.unlinked_count} 题
                  （分值合计 {templateDetail.build_meta.unlinked_score}），不可设为默认。
                </Text>
              </Card>
            )}
            <Title level={5}>题型结构</Title>
            {(templateDetail.source_paper_ids?.length || 0) <= 1 && (
              <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
                「每题」分值可编辑：填写后覆盖下方该题型全部题目明细分值；留空不覆盖已有明细分值。
              </Text>
            )}
            <Table
              size="small"
              rowKey="question_type"
              pagination={false}
              dataSource={sortTypeStructure(templateDetail.type_structure || [])}
              columns={[
                {
                  title: '题型', dataIndex: 'question_type', width: 100,
                  render: (v: string) => (questionTypeLabels[v]?.label || v),
                },
                { title: '题量', dataIndex: 'count', width: 70 },
                {
                  title: '分值', key: 'score', width: 160,
                  render: (_: any, r: any) => {
                    const singlePaper = (templateDetail.source_paper_ids?.length || 0) <= 1
                    if (!singlePaper) {
                      return r.score_each != null
                        ? `每题 ${r.score_each}`
                        : Object.entries(r.per_number || {}).map(([k, v]) => `#${k}=${v}`).join('、') || '-'
                    }
                    const unevenHint = r.score_each == null && r.per_number
                      ? Object.entries(r.per_number).map(([k, v]) => `#${k}=${v}`).join('、')
                      : ''
                    return (
                      <Space size={4} wrap>
                        <Text type="secondary" style={{ fontSize: 12 }}>每题</Text>
                        <InputNumber
                          key={`type-each-${r.question_type}-${r.score_each ?? 'empty'}`}
                          size="small"
                          min={0}
                          step={1}
                          style={{ width: 72 }}
                          placeholder="空"
                          defaultValue={r.score_each == null ? undefined : r.score_each}
                          disabled={
                            templateTypeScoreSaving === r.question_type
                            || templateScoreSavingId != null
                          }
                          onBlur={(e) => {
                            const raw = (e.target as HTMLInputElement).value?.trim()
                            // 空缺不覆盖题目明细分值
                            if (raw === '' || raw == null) return
                            const n = Number(raw)
                            if (!Number.isNaN(n)) handleTypeScoreEachSave(r.question_type, n)
                          }}
                          onPressEnter={(e) => {
                            ;(e.target as HTMLInputElement).blur()
                          }}
                        />
                        {unevenHint ? (
                          <Text type="secondary" style={{ fontSize: 12 }}>({unevenHint})</Text>
                        ) : null}
                      </Space>
                    )
                  },
                },
                { title: '小计', dataIndex: 'subtotal', width: 80 },
              ]}
            />
            {(templateDetail.source_paper_ids?.length || 0) <= 1 && (
              <>
                <Title level={5} style={{ marginTop: 20 }}>题目明细</Title>
                <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
                  来源卷逐题：题型、分值、主知识点一/二级分类。分值可直接编辑，失焦或回车后写回该题并刷新模板。
                </Text>
                <Table
                  size="small"
                  pagination={false}
                  scroll={{ y: 280 }}
                  rowKey={(r: any) => `qrow-${r.exam_paper_id}-${r.question_id}`}
                  dataSource={templateDetail.question_rows || []}
                  locale={{ emptyText: '暂无题目明细' }}
                  columns={[
                    { title: '题号', dataIndex: 'question_number', width: 60 },
                    {
                      title: '题型', dataIndex: 'question_type', width: 80,
                      render: (v: string) => questionTypeLabels[v]?.label || v,
                    },
                    {
                      title: '分值', dataIndex: 'score', width: 100,
                      render: (v: number | null, r: any) => (
                        <InputNumber
                          key={`tpl-score-${r.question_id}-${v ?? 'empty'}`}
                          size="small"
                          min={0}
                          step={1}
                          style={{ width: 72 }}
                          placeholder="空"
                          defaultValue={v == null ? undefined : v}
                          disabled={templateScoreSavingId === r.question_id}
                          onBlur={(e) => {
                            const raw = (e.target as HTMLInputElement).value?.trim()
                            if (raw === '' || raw == null) {
                              handleTemplateScoreSave(r, null)
                              return
                            }
                            const n = Number(raw)
                            if (!Number.isNaN(n)) handleTemplateScoreSave(r, n)
                          }}
                          onPressEnter={(e) => {
                            ;(e.target as HTMLInputElement).blur()
                          }}
                        />
                      ),
                    },
                    {
                      title: '一级分类', dataIndex: 'category_1', width: 120,
                      render: (v: string) => v || '—',
                    },
                    {
                      title: '二级分类', dataIndex: 'category_2', ellipsis: true,
                      render: (v: string) => v || '—',
                    },
                    {
                      title: '主知识点ID', dataIndex: 'primary_kp_id', width: 120,
                      render: (v: string) => v || '—',
                    },
                  ]}
                />
              </>
            )}
            <Title level={5} style={{ marginTop: 20 }}>知识点分值占比</Title>
            <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
              单卷：占比 = 该行分值 ÷ 该题型总分。
              多套平均：各卷先算占比，再等权平均；展示分值 = 平均占比 × 题型平均总分。
            </Text>
            <Table
              size="small"
              pagination={false}
              rowKey={(_, i) => `kp-ratio-${i}`}
              dataSource={buildKpRatioTableRows(
                templateDetail.category_score_stats,
                sortTypeStructure(templateDetail.type_structure || []),
              )}
              locale={{ emptyText: '暂无数据（需题目已挂载主知识点）' }}
              columns={[
                {
                  title: '题型',
                  dataIndex: 'question_type',
                  width: 90,
                  onCell: (r: any) => ({ rowSpan: r._typeSpan || 0 }),
                  render: (v: string, r: any) => (
                    r._typeSpan ? (questionTypeLabels[v]?.label || v) : null
                  ),
                },
                {
                  title: '知识点一级分类',
                  dataIndex: 'category_1',
                  width: 140,
                  onCell: (r: any) => ({ rowSpan: r._cat1Span || 0 }),
                  render: (v: string, r: any) => (r._cat1Span ? (v || '-') : null),
                },
                {
                  title: '知识点二级分类',
                  dataIndex: 'category_2',
                  ellipsis: true,
                  render: (v: string) => (v ? v : ''),
                },
                {
                  title: '分值',
                  dataIndex: 'score_sum',
                  width: 70,
                },
                {
                  title: '占题型的百分比',
                  dataIndex: 'score_ratio',
                  width: 120,
                  render: (v: number) => `${((v || 0) * 100).toFixed(1)}%`,
                },
              ]}
            />
          </div>
        )}
      </Drawer>

      {/* 模板总览 */}
      <Drawer
        title="结构模板"
        open={templateListVisible}
        onClose={() => setTemplateListVisible(false)}
        width={640}
      >
        <Table
          size="small"
          rowKey="id"
          loading={templateListLoading}
          dataSource={templateList}
          pagination={false}
          columns={[
            { title: '名称', dataIndex: 'name', ellipsis: true },
            {
              title: '状态', dataIndex: 'status', width: 90,
              render: (v: string, r: any) => (
                <Space size={4}>
                  <Tag color={v === 'ready' ? 'blue' : 'orange'}>{v}</Tag>
                  {r.is_default && <Tag color="green">默认</Tag>}
                </Space>
              ),
            },
            {
              title: '题型摘要', key: 'summary', width: 160,
              render: (_: any, r: any) =>
                (r.type_structure || [])
                  .map((t: any) => `${questionTypeLabels[t.question_type]?.label || t.question_type}×${t.count}`)
                  .join(' / ') || '-',
            },
            {
              title: '操作', key: 'op', width: 160,
              render: (_: any, r: any) => (
                <Space size="small">
                  <Button type="link" size="small" onClick={() => openTemplateDetail(r.id)}>查看</Button>
                  {r.is_default ? (
                    <Button type="link" size="small" onClick={() => handleUnsetDefaultTemplate(r.id)}>取消默认</Button>
                  ) : (
                    <Button
                      type="link"
                      size="small"
                      disabled={r.status !== 'ready'}
                      onClick={() => handleSetDefaultTemplate(r.id)}
                    >
                      设默认
                    </Button>
                  )}
                  {!r.is_default && (
                    <Popconfirm title="确认删除该模板？" onConfirm={() => handleDeleteTemplate(r.id)}>
                      <Button type="link" size="small" danger>删</Button>
                    </Popconfirm>
                  )}
                </Space>
              ),
            },
          ]}
        />
      </Drawer>
    </div>
  )
}

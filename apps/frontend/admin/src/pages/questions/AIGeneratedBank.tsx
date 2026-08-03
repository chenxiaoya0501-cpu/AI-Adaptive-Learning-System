import React, { useEffect, useState, useMemo, useCallback } from 'react'
import {
  Tree, Card, Typography, Empty, Spin, Select, InputNumber, Button,
  Table, Tag, Space, message, Input, Checkbox, Divider, Popconfirm, Tabs,
} from 'antd'
import { RobotOutlined, SaveOutlined, DeleteOutlined, EditOutlined } from '@ant-design/icons'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import { knowledgeApi, questionApi } from '../../api'

const { Title, Text } = Typography
const { TextArea } = Input

interface KnowledgePoint {
  id: string
  name: string
  short_name?: string
  domain: string
  category_1: string
  category_2: string
}

interface TreeNode {
  key: string
  title: string
  children?: TreeNode[]
  isLeaf?: boolean
  kpId?: string
}

interface SampleQuestion {
  id: number
  exam_paper_id?: number
  question_type: string
  content: string
  options?: Record<string, string>
  answer?: string
  analysis?: string
  difficulty: number
  bank_type: string
}

interface GeneratedQuestion {
  question_type: string
  content: string
  options?: Record<string, string> | null
  answer?: string
  analysis?: string
  difficulty: number
}

const QUESTION_TYPE_OPTIONS = [
  { value: 'choice', label: '选择题' },
  { value: 'fill', label: '填空题' },
  { value: 'answer', label: '解答题' },
]

const QUESTION_TYPE_MAP: Record<string, string> = {
  choice: '选择题', fill: '填空题', answer: '解答题', proof: '证明题',
}

const DIFFICULTY_STARS = (d: number) => '★'.repeat(d) + '☆'.repeat(5 - d)

// Unicode 上标映射
const SUPERSCRIPT_MAP: Record<string, string> = {
  '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
  '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
  '+': '⁺', '-': '⁻', 'n': 'ⁿ',
}
function toSuperscript(s: string): string {
  return s.split('').map((c) => SUPERSCRIPT_MAP[c] || c).join('')
}

// 清理 AI 生成文本：去掉 LaTeX $...$，将 ^n 转为 Unicode 上标
function stripLatex(text: string | undefined | null): string {
  if (!text) return ''
  let s = text.replace(/\$([^$]+)\$/g, '$1')
  // ^{...} → 上标（如 x^{10} → x¹⁰）
  s = s.replace(/\^{([^}]+)}/g, (_, exp) => toSuperscript(exp))
  // ^数字 → 上标（如 x^2 → x²）
  s = s.replace(/\^(\d+)/g, (_, exp) => toSuperscript(exp))
  // ^单个字符（如 a^n → aⁿ）
  s = s.replace(/\^([a-z0-9])/gi, (_, c) => SUPERSCRIPT_MAP[c] || `^${c}`)
  return s
}
function cleanOptions(opts: Record<string, string> | null | undefined): Record<string, string> | undefined {
  if (!opts) return undefined
  const cleaned: Record<string, string> = {}
  for (const [k, v] of Object.entries(opts)) {
    cleaned[k] = stripLatex(v)
  }
  return cleaned
}

/** 将纯文本数学符号转为 LaTeX（复用 QuestionBank 的逻辑） */
function plainToLatex(text: string): string | null {
  const raw = (text || '').trim()
  if (!raw || raw.includes('[IMG:')) return null
  if (/^[A-D]$/i.test(raw)) return null
  if (/^[A-Za-z]$/.test(raw)) return raw
  if (raw.includes('\\sqrt') || raw.includes('\\frac') || raw.includes('\\dfrac')) {
    return raw.replace(/^\$+|\$+$/g, '')
  }
  let t = raw
  t = t.replace(/²/g, '^{2}').replace(/³/g, '^{3}')
  t = t.replace(/⁴/g, '^{4}').replace(/⁵/g, '^{5}').replace(/⁶/g, '^{6}')
  t = t.replace(/⁷/g, '^{7}').replace(/⁸/g, '^{8}').replace(/⁹/g, '^{9}').replace(/⁰/g, '^{0}')
  t = t.replace(/∛\s*\(([^)]+)\)/g, '\\sqrt[3]{$1}')
  t = t.replace(/∛\s*(\d+(?:\.\d+)?|[A-Za-z])/g, '\\sqrt[3]{$1}')
  t = t.replace(/∜\s*\(([^)]+)\)/g, '\\sqrt[4]{$1}')
  t = t.replace(/∜\s*(\d+(?:\.\d+)?|[A-Za-z])/g, '\\sqrt[4]{$1}')
  t = t.replace(/√\s*\(([^)]+)\)/g, '\\sqrt{$1}')
  t = t.replace(/(-?\d*)√\s*(\d+(?:\.\d+)?|[A-Za-z])/g, (_, a, b) => (a ? `${a}\\sqrt{${b}}` : `\\sqrt{${b}}`))
  const compound = t.match(/^(\([^)]+\)|[A-Za-z0-9^{}+\-]+)\/([A-Za-z0-9]+)(\\sqrt\{[^}]+\})$/)
  if (compound) return `\\dfrac{${compound[1]}}{${compound[2]}}${compound[3]}`
  const fracParen = t.match(/^(.+?)\/\((.+)\)$/)
  if (fracParen) return `\\dfrac{${fracParen[1]}}{${fracParen[2]}}`
  const fracGroup = t.match(/^\(([^)]+)\)\/([A-Za-z0-9]+)$/)
  if (fracGroup) return `\\dfrac{${fracGroup[1]}}{${fracGroup[2]}}`
  if (/^-?\d+(?:\.\d+)?\/\d+(?:\.\d+)?$/.test(t)) {
    const [a, b] = t.split('/')
    return `\\dfrac{${a}}{${b}}`
  }
  if (/^[A-Za-z0-9^{}\-]+\/[A-Za-z0-9^{}\-+]+$/.test(t) && t.includes('/')) {
    const slash = t.indexOf('/')
    return `\\dfrac{${t.slice(0, slash)}}{${t.slice(slash + 1)}}`
  }
  t = t.replace(/≤/g, '\\le ').replace(/≥/g, '\\ge ').replace(/°/g, '^{\\circ}')
  if (/\\sqrt|\\dfrac|\\frac|\\le|\\ge|\^\{/.test(t) || /[≤≥²³]/.test(raw) || /√|∛|∜/.test(raw) || /\//.test(raw)) {
    return t
  }
  return null
}

function renderKatexSpan(latex: string, key: React.Key) {
  try {
    const html = katex.renderToString(latex, {
      throwOnError: false, displayMode: false, strict: 'ignore', output: 'html',
    })
    return (
      <span key={key} className="katex-answer" style={{ display: 'inline', verticalAlign: 'middle', fontSize: 'inherit', lineHeight: 'inherit' }}
        dangerouslySetInnerHTML={{ __html: html }} />
    )
  } catch { return <span key={key}>{latex}</span> }
}

const MATH_CHUNK_RE =
  /(\([^)]+\)\/[A-Za-z0-9]+[√∛∜]\([^)]+\)|\([^)]+\)\/[A-Za-z0-9]+|-?\d*[√∛∜]\s*\([^)]+\)|-?\d*[√∛∜]\s*[\dA-Za-z]+(?:\.\d+)?|-?\d+(?:\.\d+)?\/\d+(?:\.\d+)?|[A-Za-z][²]?\/\([A-Za-z0-9²³+\-]+\)|[A-Za-z0-9²³^{}\-]+\/[A-Za-z0-9²³^{}\-+]+|(?<![A-Za-z])[A-Za-z](?=\s*=)|[≤≥]|[²³])/g

function renderMathText(text: string, key?: React.Key) {
  const raw = text || ''
  if (!raw) return <span key={key} />
  const wholeLatex = plainToLatex(raw)
  if (wholeLatex && !/[\u4e00-\u9fff]/.test(raw)) return renderKatexSpan(wholeLatex, key ?? 'm')
  const parts: React.ReactNode[] = []
  let last = 0, mi = 0
  MATH_CHUNK_RE.lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = MATH_CHUNK_RE.exec(raw)) !== null) {
    if (m.index > last) parts.push(<span key={`${key}-t${mi}`}>{raw.slice(last, m.index)}</span>)
    const chunk = m[0]
    const latex = plainToLatex(chunk)
    parts.push(latex ? renderKatexSpan(latex, `${key}-m${mi}`) : <span key={`${key}-m${mi}`}>{chunk}</span>)
    last = m.index + chunk.length
    mi++
  }
  if (last < raw.length) parts.push(<span key={`${key}-t${mi}`}>{raw.slice(last)}</span>)
  if (!parts.length) return <span key={key}>{raw}</span>
  return <span key={key}>{parts}</span>
}

function renderTextOrMathChunks(text: string, keyPrefix: string) {
  const lines = text.split('\n')
  return lines.map((line, li) => (
    <React.Fragment key={`${keyPrefix}-L${li}`}>
      {li > 0 ? <br /> : null}
      {renderMathText(line, `${keyPrefix}-T${li}`)}
    </React.Fragment>
  ))
}

// 解析 [IMG:filename,W,H] 占位符并渲染为图片，数学公式用 KaTeX 渲染
function renderRichContent(text: string, paperId?: number) {
  if (!text) return <span>-</span>
  const parts = text.split(/(\[IMG:[^\]]+\])/g)
  return (
    <span style={{ lineHeight: '32px' }}>
      {parts.map((part, idx) => {
        const m = part.match(/\[IMG:([^,\]]+)(?:,([\d.]+),([\d.]+))?\]/)
        if (m && paperId) {
          const filename = m[1]
          const wPt = m[2] ? parseFloat(m[2]) : 0
          const hPt = m[3] ? parseFloat(m[3]) : 0
          const url = `/uploads/papers/paper_${paperId}_images/${filename}`
          let style: React.CSSProperties = { verticalAlign: 'middle', margin: '0 2px' }
          if (hPt > 0 && wPt > 0) {
            const scale = Math.min(1.33, 28 / hPt)
            style = { ...style, height: hPt * scale, width: wPt * scale }
          } else {
            style = { ...style, height: 24 }
          }
          return <img key={idx} src={url} alt={filename} style={style} />
        }
        return <React.Fragment key={idx}>{renderTextOrMathChunks(part, `p${idx}`)}</React.Fragment>
      })}
    </span>
  )
}

export default function AIGeneratedBank() {
  const [points, setPoints] = useState<KnowledgePoint[]>([])
  const [treeLoading, setTreeLoading] = useState(false)
  const [selectedKp, setSelectedKp] = useState<KnowledgePoint | null>(null)

  // AI已生成题目（当前知识点下已保存的AI题）
  const [aiQuestions, setAiQuestions] = useState<SampleQuestion[]>([])
  const [aiQuestionsTotal, setAiQuestionsTotal] = useState(0)
  const [aiQuestionsPage, setAiQuestionsPage] = useState(1)
  const [aiQuestionsLoading, setAiQuestionsLoading] = useState(false)

  // Sample questions browser
  const [samples, setSamples] = useState<SampleQuestion[]>([])
  const [samplesTotal, setSamplesTotal] = useState(0)
  const [samplesPage, setSamplesPage] = useState(1)
  const [samplesLoading, setSamplesLoading] = useState(false)
  const [sampleBankType, setSampleBankType] = useState<string | undefined>(undefined)
  const [sampleQType, setSampleQType] = useState<string | undefined>(undefined)
  const [selectedSampleIds, setSelectedSampleIds] = useState<number[]>([])
  const [selectedSamples, setSelectedSamples] = useState<SampleQuestion[]>([])

  // Generation config
  const [questionType, setQuestionType] = useState('choice')
  const [genCount, setGenCount] = useState(3)
  const [genDifficulty, setGenDifficulty] = useState<number | undefined>(undefined)
  const [generating, setGenerating] = useState(false)

  // Generated results
  const [generatedList, setGeneratedList] = useState<GeneratedQuestion[]>([])
  const [editingIdx, setEditingIdx] = useState<number | null>(null)
  const [editForm, setEditForm] = useState<GeneratedQuestion | null>(null)
  const [savingIdx, setSavingIdx] = useState<number | null>(null)

  useEffect(() => { fetchPoints() }, [])

  const fetchPoints = async () => {
    setTreeLoading(true)
    try {
      const all: KnowledgePoint[] = []
      let page = 1
      const pageSize = 500
      while (true) {
        const res = await knowledgeApi.listPoints({ page, page_size: pageSize })
        const items = res.data.items || []
        all.push(...items)
        if (items.length < pageSize || all.length >= (res.data.total || Infinity)) break
        page++
      }
      setPoints(all)
    } catch { /* ignore */ }
    finally { setTreeLoading(false) }
  }

  // Load saved AI questions for current KP
  const fetchAiQuestions = useCallback(async (kpId: string, page: number) => {
    setAiQuestionsLoading(true)
    try {
      const params: any = { page, page_size: 10, primary_kp_id: kpId, bank_type: 'ai' }
      const res = await questionApi.listQuestions(params)
      setAiQuestions(res.data.items || [])
      setAiQuestionsTotal(res.data.total || 0)
    } catch { setAiQuestions([]); setAiQuestionsTotal(0) }
    finally { setAiQuestionsLoading(false) }
  }, [])

  // Load sample questions with filters & pagination — always scoped to current KP
  const fetchSamples = useCallback(async (kpId: string, page: number, bankType?: string, qType?: string) => {
    setSamplesLoading(true)
    try {
      const params: any = { page, page_size: 10, primary_kp_id: kpId }
      if (bankType) params.bank_type = bankType
      if (qType) params.question_type = qType
      const res = await questionApi.listQuestions(params)
      setSamples(res.data.items || [])
      setSamplesTotal(res.data.total || 0)
    } catch { setSamples([]); setSamplesTotal(0) }
    finally { setSamplesLoading(false) }
  }, [])

  // When kp changes, reset state and load samples + AI questions
  useEffect(() => {
    if (selectedKp) {
      setSamplesPage(1)
      setSampleBankType(undefined)
      setSampleQType(undefined)
      setSelectedSampleIds([])
      setSelectedSamples([])
      setGeneratedList([])
      setEditingIdx(null)
      setAiQuestionsPage(1)
      fetchSamples(selectedKp.id, 1)
      fetchAiQuestions(selectedKp.id, 1)
    } else {
      setSamples([])
      setSamplesTotal(0)
      setSelectedSampleIds([])
      setSelectedSamples([])
      setGeneratedList([])
      setAiQuestions([])
      setAiQuestionsTotal(0)
    }
  }, [selectedKp, fetchSamples, fetchAiQuestions])

  // Refetch when filters or page change (but not on initial kp change)
  const handleSampleFilterChange = (bankType?: string, qType?: string) => {
    setSampleBankType(bankType)
    setSampleQType(qType)
    setSamplesPage(1)
    if (!selectedKp) return
    fetchSamples(selectedKp.id, 1, bankType, qType)
  }

  const handleSamplePageChange = (page: number) => {
    setSamplesPage(page)
    if (!selectedKp) return
    fetchSamples(selectedKp.id, page, sampleBankType, sampleQType)
  }

  // Track selected samples (keep full objects for display)
  const toggleSample = (record: SampleQuestion, checked: boolean) => {
    if (checked) {
      setSelectedSampleIds((prev) => [...prev, record.id])
      setSelectedSamples((prev) => [...prev, record])
    } else {
      setSelectedSampleIds((prev) => prev.filter((id) => id !== record.id))
      setSelectedSamples((prev) => prev.filter((s) => s.id !== record.id))
    }
  }

  // Build three-level tree
  const treeData = useMemo(() => {
    const domainMap = new Map<string, Map<string, Map<string, KnowledgePoint[]>>>()
    for (const kp of points) {
      const domain = kp.domain || '未分类'
      const cat1 = kp.category_1 || '未分类'
      const cat2 = kp.category_2 || '未分类'
      if (!domainMap.has(domain)) domainMap.set(domain, new Map())
      const cat1Map = domainMap.get(domain)!
      if (!cat1Map.has(cat1)) cat1Map.set(cat1, new Map())
      const cat2Map = cat1Map.get(cat1)!
      if (!cat2Map.has(cat2)) cat2Map.set(cat2, [])
      cat2Map.get(cat2)!.push(kp)
    }
    const tree: TreeNode[] = []
    for (const [domain, cat1Map] of domainMap) {
      const domainNode: TreeNode = { key: `domain:${domain}`, title: domain, children: [] }
      for (const [cat1, cat2Map] of cat1Map) {
        const cat1Node: TreeNode = { key: `cat1:${domain}/${cat1}`, title: cat1, children: [] }
        for (const [cat2, kps] of cat2Map) {
          cat1Node.children!.push({
            key: `cat2:${domain}/${cat1}/${cat2}`,
            title: `${cat2}（${kps.length}）`,
            children: kps.map((kp) => ({
              key: `kp:${kp.id}`,
              title: kp.short_name || kp.name,
              isLeaf: true,
              kpId: kp.id,
            })),
          })
        }
        domainNode.children!.push(cat1Node)
      }
      tree.push(domainNode)
    }
    return tree
  }, [points])

  const handleSelect = (selectedKeys: React.Key[]) => {
    if (!selectedKeys.length) { setSelectedKp(null); return }
    const key = String(selectedKeys[0])
    if (key.startsWith('kp:')) {
      const kpId = key.replace('kp:', '')
      setSelectedKp(points.find((p) => p.id === kpId) || null)
    } else {
      setSelectedKp(null)
    }
  }

  // AI Generate
  const handleGenerate = async () => {
    if (!selectedKp) return
    setGenerating(true)
    try {
      const res = await questionApi.aiGenerate({
        kp_id: selectedKp.id,
        question_type: questionType,
        count: genCount,
        sample_ids: selectedSampleIds.length > 0 ? selectedSampleIds : undefined,
        difficulty: genDifficulty,
      })
      const items = res.data.questions || []
      setGeneratedList(items)
      if (items.length > 0) {
        message.success(`成功生成 ${items.length} 道题目，请审核`)
      } else {
        message.warning('LLM 未返回题目，请调整参数重试')
      }
    } catch (err: any) {
      message.error(err?.response?.data?.detail || 'AI 生成失败，请检查 LLM 配置')
    } finally {
      setGenerating(false)
    }
  }

  // Edit a generated question
  const startEdit = (idx: number) => {
    setEditingIdx(idx)
    setEditForm({ ...generatedList[idx] })
  }
  const cancelEdit = () => { setEditingIdx(null); setEditForm(null) }
  const saveEdit = () => {
    if (editingIdx === null || !editForm) return
    const updated = [...generatedList]
    updated[editingIdx] = { ...editForm }
    setGeneratedList(updated)
    setEditingIdx(null)
    setEditForm(null)
    message.success('已更新')
  }

  // Delete a generated question
  const deleteGenerated = (idx: number) => {
    const updated = generatedList.filter((_, i) => i !== idx)
    setGeneratedList(updated)
  }

  // Save a generated question to database as AI question
  const saveToDb = async (idx: number) => {
    if (!selectedKp) return
    setSavingIdx(idx)
    const q = generatedList[idx]
    try {
      await questionApi.createQuestion({
        bank_type: 'ai',
        question_type: q.question_type,
        content: stripLatex(q.content),
        options: cleanOptions(q.options),
        answer: stripLatex(q.answer),
        analysis: stripLatex(q.analysis),
        difficulty: q.difficulty,
        primary_kp_id: selectedKp.id,
        source: 'AI生成',
      })
      message.success('已保存到AI题库')
      const updated = [...generatedList]
      updated.splice(idx, 1)
      setGeneratedList(updated)
      // Refresh AI questions list and samples
      fetchAiQuestions(selectedKp.id, aiQuestionsPage)
      fetchSamples(selectedKp.id, samplesPage, sampleBankType, sampleQType)
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '保存失败')
    } finally {
      setSavingIdx(null)
    }
  }

  // Save all to DB
  const saveAllToDb = async () => {
    if (!selectedKp || generatedList.length === 0) return
    setSavingIdx(-1)
    let ok = 0
    for (const q of generatedList) {
      try {
        await questionApi.createQuestion({
          bank_type: 'ai',
          question_type: q.question_type,
          content: stripLatex(q.content),
          options: cleanOptions(q.options),
          answer: stripLatex(q.answer),
          analysis: stripLatex(q.analysis),
          difficulty: q.difficulty,
          primary_kp_id: selectedKp.id,
          source: 'AI生成',
        })
        ok++
      } catch { /* skip */ }
    }
    message.success(`已保存 ${ok} 道题到AI题库`)
    setGeneratedList([])
    fetchAiQuestions(selectedKp.id, 1)
    setAiQuestionsPage(1)
    fetchSamples(selectedKp.id, samplesPage, sampleBankType, sampleQType)
    setSavingIdx(null)
  }

  // Sample table columns
  const sampleColumns = [
    {
      title: '',
      width: 40,
      render: (_: any, record: SampleQuestion) => (
        <Checkbox
          checked={selectedSampleIds.includes(record.id)}
          onChange={(e) => toggleSample(record, e.target.checked)}
        />
      ),
    },
    { title: 'ID', dataIndex: 'id', width: 50 },
    {
      title: '题型', dataIndex: 'question_type', width: 70,
      render: (v: string) => <Tag>{QUESTION_TYPE_MAP[v] || v}</Tag>,
    },
    {
      title: '来源', dataIndex: 'bank_type', width: 70,
      render: (v: string) => <Tag color={v === 'real' ? 'blue' : v === 'ai' ? 'green' : 'orange'}>{v === 'real' ? '真题' : v === 'ai' ? 'AI' : '模拟'}</Tag>,
    },
    {
      title: '难度', dataIndex: 'difficulty', width: 90,
      render: (v: number) => <span style={{ color: '#faad14', fontSize: 12 }}>{DIFFICULTY_STARS(v)}</span>,
    },
    {
      title: '题目内容', dataIndex: 'content', ellipsis: false, width: 360,
      render: (_: string, record: SampleQuestion) => {
        let display = record.content || ''
        if (record.options && typeof record.options === 'object') {
          const optLines = Object.entries(record.options)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([k, val]) => `${k}. ${val}`)
            .join('  ')
          if (optLines) display = display + '\n' + optLines
        }
        return (
          <div style={{ lineHeight: '24px', whiteSpace: 'pre-wrap', fontSize: 13 }}>
            {renderRichContent(display, record.exam_paper_id)}
          </div>
        )
      },
    },
  ]

  // Render the right panel
  const renderRightPanel = () => {
    if (!selectedKp) {
      return <Empty description="请从左侧选择一个知识点" style={{ marginTop: 80 }} />
    }

    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        {/* KP info - always visible at top */}
        <div style={{ marginBottom: 12, padding: '10px 16px', background: '#f6ffed', border: '1px solid #b7eb8f', borderRadius: 8, flexShrink: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 2 }}>
            {selectedKp.short_name || selectedKp.name}
          </div>
          {selectedKp.name && selectedKp.name !== selectedKp.short_name && (
            <div style={{ color: '#555', fontSize: 13, lineHeight: 1.5 }}>{selectedKp.name}</div>
          )}
        </div>

        {/* Tabs layout */}
        <Tabs
          defaultActiveKey="generate"
          style={{ flex: 1, minHeight: 0 }}
          items={[
            {
              key: 'generate',
              label: `AI出题${generatedList.length > 0 ? `（${generatedList.length}待保存）` : ''}`,
              children: (
                <div style={{ overflow: 'auto' }}>
                  {/* Sample questions browser */}
                  <div style={{ marginBottom: 12 }}>
                    <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 8 }}>参考题目（从真题/模拟题库中选择样本）</div>
                    <Space wrap style={{ marginBottom: 8 }}>
                      <span>题库：</span>
                      <Select
                        value={sampleBankType}
                        onChange={(v) => handleSampleFilterChange(v, sampleQType)}
                        allowClear
                        placeholder="全部"
                        style={{ width: 110 }}
                        options={[{ value: 'real', label: '真题库' }, { value: 'mock', label: '模拟题库' }]}
                      />
                      <span>题型：</span>
                      <Select
                        value={sampleQType}
                        onChange={(v) => handleSampleFilterChange(sampleBankType, v)}
                        allowClear
                        placeholder="全部"
                        style={{ width: 110 }}
                        options={QUESTION_TYPE_OPTIONS}
                      />
                      <Text type="secondary">共 {samplesTotal} 题</Text>
                    </Space>
                    <Table
                      dataSource={samples}
                      columns={sampleColumns}
                      rowKey="id"
                      size="small"
                      loading={samplesLoading}
                      pagination={{
                        current: samplesPage,
                        pageSize: 5,
                        total: samplesTotal,
                        size: 'small',
                        showSizeChanger: false,
                        onChange: handleSamplePageChange,
                      }}
                      style={{ marginBottom: 8 }}
                    />
                    {selectedSamples.length > 0 && (
                      <div style={{ marginBottom: 12, padding: '8px 12px', background: '#e6f7ff', border: '1px solid #91d5ff', borderRadius: 6 }}>
                        <Text strong>已选 {selectedSamples.length} 道样本题：</Text>
                        <div style={{ marginTop: 4 }}>
                          {selectedSamples.map((s) => (
                            <Tag
                              key={s.id}
                              closable
                              onClose={() => toggleSample(s, false)}
                              style={{ marginBottom: 4 }}
                            >
                              #{s.id} {QUESTION_TYPE_MAP[s.question_type] || s.question_type}
                              （{s.bank_type === 'real' ? '真题' : s.bank_type === 'ai' ? 'AI' : '模拟'}）
                            </Tag>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Generation config */}
                  <div style={{ padding: '12px 0', borderTop: '1px solid #f0f0f0' }}>
                    <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 8 }}>AI出题设置</div>
                    <Space wrap style={{ marginBottom: 16 }}>
                      <span>题型：</span>
                      <Select value={questionType} onChange={setQuestionType} style={{ width: 120 }} options={QUESTION_TYPE_OPTIONS} />
                      <span>数量：</span>
                      <InputNumber min={1} max={10} value={genCount} onChange={(v) => setGenCount(v || 3)} style={{ width: 70 }} />
                      <span>难度：</span>
                      <Select
                        value={genDifficulty}
                        onChange={setGenDifficulty}
                        allowClear
                        placeholder="不限"
                        style={{ width: 100 }}
                        options={[1, 2, 3, 4, 5].map((d) => ({ value: d, label: `${d} 级` }))}
                      />
                      <Button
                        type="primary"
                        icon={<RobotOutlined />}
                        loading={generating}
                        onClick={handleGenerate}
                      >
                        {generating ? 'AI 生成中…' : `AI 生成${selectedSampleIds.length > 0 ? `（${selectedSampleIds.length}样本）` : ''}`}
                      </Button>
                    </Space>
                  </div>

                  {/* Generated results */}
                  {generatedList.length > 0 && (
                    <div style={{ borderTop: '1px solid #f0f0f0', paddingTop: 12 }}>
                      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
                        <span style={{ fontWeight: 600, fontSize: 14 }}>生成结果（{generatedList.length} 题）</span>
                        <Button
                          type="link"
                          icon={<SaveOutlined />}
                          loading={savingIdx === -1}
                          onClick={saveAllToDb}
                          style={{ marginLeft: 8 }}
                        >
                          全部保存到AI题库
                        </Button>
                      </div>
                      {generatedList.map((q, idx) => (
                        <Card
                          key={idx}
                          size="small"
                          style={{ marginBottom: 12, border: '1px solid #d9d9d9' }}
                          title={
                            <Space>
                              <Tag color="green">第{idx + 1}题</Tag>
                              <Tag>{QUESTION_TYPE_MAP[q.question_type] || q.question_type}</Tag>
                              <span style={{ color: '#faad14', fontSize: 12 }}>{DIFFICULTY_STARS(q.difficulty)}</span>
                            </Space>
                          }
                          extra={
                            <Space>
                              <Button size="small" icon={<EditOutlined />} onClick={() => startEdit(idx)}>编辑</Button>
                              <Button size="small" icon={<SaveOutlined />} type="primary" loading={savingIdx === idx} onClick={() => saveToDb(idx)}>保存</Button>
                              <Button size="small" icon={<DeleteOutlined />} danger onClick={() => deleteGenerated(idx)}>删除</Button>
                            </Space>
                          }
                        >
                          {editingIdx === idx && editForm ? (
                            <div>
                              <div style={{ marginBottom: 8 }}>
                                <Text strong>题目内容：</Text>
                                <TextArea rows={3} value={editForm.content} onChange={(e) => setEditForm({ ...editForm, content: e.target.value })} />
                              </div>
                              {editForm.question_type === 'choice' && editForm.options && (
                                <div style={{ marginBottom: 8 }}>
                                  <Text strong>选项：</Text>
                                  {Object.entries(editForm.options).map(([k, v]) => (
                                    <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
                                      <Tag>{k}</Tag>
                                      <Input
                                        value={v}
                                        onChange={(e) => setEditForm({
                                          ...editForm,
                                          options: { ...editForm.options!, [k]: e.target.value },
                                        })}
                                      />
                                    </div>
                                  ))}
                                </div>
                              )}
                              <div style={{ marginBottom: 8 }}>
                                <Text strong>答案：</Text>
                                <TextArea rows={2} value={editForm.answer || ''} onChange={(e) => setEditForm({ ...editForm, answer: e.target.value })} />
                              </div>
                              <div style={{ marginBottom: 8 }}>
                                <Text strong>解析：</Text>
                                <TextArea rows={3} value={editForm.analysis || ''} onChange={(e) => setEditForm({ ...editForm, analysis: e.target.value })} />
                              </div>
                              <div style={{ marginBottom: 8 }}>
                                <Space>
                                  <span>难度：</span>
                                  <InputNumber min={1} max={5} value={editForm.difficulty} onChange={(v) => setEditForm({ ...editForm, difficulty: v || 3 })} />
                                </Space>
                              </div>
                              <Space>
                                <Button type="primary" size="small" onClick={saveEdit}>确认修改</Button>
                                <Button size="small" onClick={cancelEdit}>取消</Button>
                              </Space>
                            </div>
                          ) : (
                            <div>
                              <div style={{ marginBottom: 8, lineHeight: 1.8 }}>{renderTextOrMathChunks(stripLatex(q.content), `gen${idx}-c`)}</div>
                              {q.question_type === 'choice' && q.options && (
                                <div style={{ marginBottom: 8, paddingLeft: 12 }}>
                                  {Object.entries(q.options).map(([k, v]) => (
                                    <div key={k}><Tag color={k === q.answer ? 'green' : 'default'}>{k}</Tag> {renderMathText(stripLatex(v), `gen${idx}-o${k}`)}</div>
                                  ))}
                                </div>
                              )}
                              <div style={{ marginBottom: 4 }}>
                                <Text type="success" strong>答案：</Text>
                                {renderMathText(stripLatex(q.answer) || '—', `gen${idx}-a`)}
                              </div>
                              {q.analysis && (
                                <div style={{ color: '#555', fontSize: 13 }}>
                                  <Text type="secondary" strong>解析：</Text> {renderTextOrMathChunks(stripLatex(q.analysis), `gen${idx}-an`)}
                                </div>
                              )}
                            </div>
                          )}
                        </Card>
                      ))}
                    </div>
                  )}
                </div>
              ),
            },
            {
              key: 'questions',
              label: `AI题目（${aiQuestionsTotal}）`,
              children: (
                <div style={{ overflow: 'auto' }}>
                  {aiQuestionsTotal > 0 ? (
                    <Table
                      dataSource={aiQuestions}
                      rowKey="id"
                      size="small"
                      loading={aiQuestionsLoading}
                      pagination={{
                        current: aiQuestionsPage,
                        pageSize: 10,
                        total: aiQuestionsTotal,
                        size: 'small',
                        showTotal: (t) => `共 ${t} 题`,
                        onChange: (p) => { setAiQuestionsPage(p); if (selectedKp) fetchAiQuestions(selectedKp.id, p) },
                      }}
                      columns={[
                        { title: 'ID', dataIndex: 'id', width: 50 },
                        {
                          title: '题型', dataIndex: 'question_type', width: 70,
                          render: (v: string) => <Tag>{QUESTION_TYPE_MAP[v] || v}</Tag>,
                        },
                        {
                          title: '难度', dataIndex: 'difficulty', width: 80,
                          render: (v: number) => <span style={{ color: '#faad14', fontSize: 12 }}>{DIFFICULTY_STARS(v)}</span>,
                        },
                        {
                          title: '题目内容', dataIndex: 'content',
                          render: (_: string, record: SampleQuestion) => {
                            let display = record.content || ''
                            if (record.question_type === 'choice' && record.options && typeof record.options === 'object') {
                              const optStr = Object.entries(record.options)
                                .sort(([a], [b]) => a.localeCompare(b))
                                .map(([k, val]) => `${k}. ${val}`)
                                .join('  ')
                              if (optStr) display = display + '\n' + optStr
                            }
                            return (
                              <div style={{ maxHeight: 80, overflow: 'auto', lineHeight: '21px', whiteSpace: 'pre-wrap', fontSize: 13 }}>
                                {renderRichContent(display, record.exam_paper_id)}
                              </div>
                            )
                          },
                        },
                        {
                          title: '答案', dataIndex: 'answer', width: 180,
                          render: (v: string, record: SampleQuestion) => {
                            const text = v || ''
                            if (!text) return <Text type="secondary">-</Text>
                            return (
                              <div style={{ maxHeight: 60, overflow: 'auto', lineHeight: '20px', whiteSpace: 'pre-wrap', fontSize: 13 }}>
                                {renderTextOrMathChunks(text, `aiq-ans-${record.id}`)}
                              </div>
                            )
                          },
                        },
                        {
                          title: '操作', width: 60,
                          render: (_: any, record: SampleQuestion) => (
                            <Popconfirm
                              title="确认删除该题目？"
                              onConfirm={async () => {
                                try {
                                  await questionApi.deleteQuestion(record.id)
                                  message.success('已删除')
                                  if (selectedKp) fetchAiQuestions(selectedKp.id, aiQuestionsPage)
                                } catch { message.error('删除失败') }
                              }}
                              okText="确认"
                              cancelText="取消"
                            >
                              <Button type="link" size="small" danger icon={<DeleteOutlined />} />
                            </Popconfirm>
                          ),
                        },
                      ]}
                    />
                  ) : (
                    <Empty description="暂无已保存的AI题目，请在「AI出题」标签中生成" style={{ marginTop: 40 }} />
                  )}
                </div>
              ),
            },
          ]}
        />
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', gap: 16, height: 'calc(100vh - 160px)' }}>
      {/* Left: Knowledge Point Tree */}
      <Card
        size="small"
        title="知识点目录"
        style={{ width: 320, flexShrink: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
        bodyStyle={{ flex: 1, overflow: 'auto', padding: '8px 4px' }}
      >
        {treeLoading ? (
          <div style={{ textAlign: 'center', padding: 48 }}><Spin /></div>
        ) : treeData.length === 0 ? (
          <Empty description="暂无知识点数据" />
        ) : (
          <Tree
            treeData={treeData}
            onSelect={handleSelect}
            showLine
            blockNode
            defaultExpandedKeys={treeData.slice(0, 1).map((n) => n.key)}
          />
        )}
      </Card>

      {/* Right: Content area */}
      <Card
        size="small"
        style={{ flex: 1, overflow: 'auto' }}
        bodyStyle={{ padding: 24 }}
      >
        <Title level={4} style={{ marginTop: 0 }}>AI生成题库</Title>
        {renderRightPanel()}
      </Card>
    </div>
  )
}

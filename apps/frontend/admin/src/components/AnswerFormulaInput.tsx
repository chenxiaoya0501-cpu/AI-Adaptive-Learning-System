import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Input, Radio, Space, Typography } from 'antd'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import 'mathlive'
import 'mathlive/static.css'
import 'mathlive/fonts.css'
import type { MathfieldElement } from 'mathlive'

const { Text } = Typography
const { TextArea } = Input

/** 读取 latex 中从 start（指向 `{`）起的平衡花括号内容 */
function readBalanced(s: string, start: number): { inner: string; end: number } | null {
  if (s[start] !== '{') return null
  let depth = 0
  for (let i = start; i < s.length; i++) {
    if (s[i] === '{') depth++
    else if (s[i] === '}') {
      depth--
      if (depth === 0) return { inner: s.slice(start + 1, i), end: i + 1 }
    }
  }
  return null
}

function replaceLatexCommand(
  s: string,
  cmd: string,
  replacer: (...args: string[]) => string,
  arity: number,
): string {
  let out = ''
  let i = 0
  while (i < s.length) {
    const idx = s.indexOf(cmd, i)
    if (idx < 0) {
      out += s.slice(i)
      break
    }
    out += s.slice(i, idx)
    let p = idx + cmd.length
    while (p < s.length && /\s/.test(s[p])) p++
    const args: string[] = []
    let ok = true
    for (let a = 0; a < arity; a++) {
      while (p < s.length && /\s/.test(s[p])) p++
      const bal = readBalanced(s, p)
      if (!bal) {
        ok = false
        break
      }
      args.push(bal.inner)
      p = bal.end
    }
    if (!ok) {
      out += s[idx]
      i = idx + 1
      continue
    }
    out += replacer(...args)
    i = p
  }
  return out
}

/** 纯文本 / 简易 latex → KaTeX/MathLive 用的 latex */
export function plainToLatex(text: string): string {
  const raw = (text || '').trim()
  if (!raw) return ''
  if (raw.includes('\\sqrt') || raw.includes('\\frac') || raw.includes('\\dfrac') || raw.includes('\\le')) {
    return raw.replace(/^\$+|\$+$/g, '')
  }
  let t = raw
  t = t.replace(/²/g, '^{2}').replace(/³/g, '^{3}')
  t = t.replace(/√\s*(\d+(?:\.\d+)?|[A-Za-z])/g, '\\sqrt{$1}')
  // k^2/(2-k^2) 或 k²/(2-k²)
  const frac = t.match(/^(.+?)\/\((.+)\)$/) || t.match(/^([^/]+)\/([^/]+)$/)
  if (frac && (/\^|²|³|[a-zA-Z]/.test(frac[1] + frac[2]) || frac[0].includes('('))) {
    return `\\frac{${frac[1]}}{${frac[2]}}`
  }
  if (/^-?\d+(?:\.\d+)?\/\d+(?:\.\d+)?$/.test(t)) {
    const [a, b] = t.split('/')
    return `\\frac{${a}}{${b}}`
  }
  t = t.replace(/≤/g, '\\le ').replace(/≥/g, '\\ge ').replace(/°/g, '^{\\circ}')
  return t
}

/** MathLive latex → 题库存储用的可读纯文本（保留分式 / 幂次结构） */
export function latexToPlain(latex: string): string {
  let s = (latex || '').trim()
  if (!s) return ''
  s = s.replace(/\\dfrac/g, '\\frac')
  // \sqrt{...}
  s = replaceLatexCommand(s, '\\sqrt', (inner) => `√${latexToPlain(inner)}`, 1)
  s = s.replace(/\\sqrt\s*([0-9A-Za-z]+)/g, '√$1')
  // \frac{a}{b} → a/b ，分母含 +− 时加括号
  {
    let next = ''
    let i = 0
    const src = s
    while (i < src.length) {
      const idx = src.indexOf('\\frac', i)
      if (idx < 0) {
        next += src.slice(i)
        break
      }
      next += src.slice(i, idx)
      let p = idx + 5
      while (p < src.length && /\s/.test(src[p])) p++
      const a = readBalanced(src, p)
      if (!a) {
        next += src[idx]
        i = idx + 1
        continue
      }
      p = a.end
      while (p < src.length && /\s/.test(src[p])) p++
      const b = readBalanced(src, p)
      if (!b) {
        next += src[idx]
        i = idx + 1
        continue
      }
      const num = latexToPlain(a.inner)
      let den = latexToPlain(b.inner)
      if (/[+\-×·]/.test(den) && !(den.startsWith('(') && den.endsWith(')'))) {
        den = `(${den})`
      }
      next += `${num}/${den}`
      i = b.end
    }
    s = next
  }
  // ^{2} / ^2 → ²（平衡花括号，避免 k^{2} 剥坏）
  {
    let next = ''
    let i = 0
    while (i < s.length) {
      if (s[i] === '^' && s[i + 1] === '{') {
        const bal = readBalanced(s, i + 1)
        if (bal) {
          const inner = latexToPlain(bal.inner)
          next += inner === '2' ? '²' : inner === '3' ? '³' : `^${inner}`
          i = bal.end
          continue
        }
      }
      if (s[i] === '^' && /[0-9]/.test(s[i + 1] || '')) {
        next += s[i + 1] === '2' ? '²' : s[i + 1] === '3' ? '³' : `^${s[i + 1]}`
        i += 2
        continue
      }
      next += s[i]
      i++
    }
    s = next
  }
  s = s.replace(/\\le\b/g, '≤').replace(/\\ge\b/g, '≥')
  s = s.replace(/\\circ/g, '°')
  s = s.replace(/\\left/g, '').replace(/\\right/g, '')
  s = s.replace(/\\cdot/g, '·').replace(/\\times/g, '×')
  s = s.replace(/\\pi/g, 'π')
  s = s.replace(/\{\}/g, '')
  // 残余未解析命令：去掉反斜杠，保留内容；勿整段删 {}
  s = s.replace(/\\([A-Za-z]+)/g, '$1')
  s = s.replace(/\\/g, '')
  s = s.replace(/\s+/g, '')
  return s
}

function KaTeXPreview({ text }: { text: string }) {
  const html = useMemo(() => {
    const latex = plainToLatex(text)
    if (!latex) return ''
    try {
      return katex.renderToString(latex, {
        throwOnError: false,
        displayMode: false,
        strict: 'ignore',
        output: 'html',
      })
    } catch {
      return ''
    }
  }, [text])

  if (!text?.trim()) {
    return <Text type="secondary">预览为空</Text>
  }
  if (!html) {
    return <span>{text}</span>
  }
  return (
    <span
      className="katex-answer"
      style={{ display: 'inline-block', lineHeight: 1.4, fontSize: 18 }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

export type AnswerFormulaInputProps = {
  value?: string
  onChange?: (v: string) => void
  rows?: number
}

/**
 * 答案编辑：支持公式渲染预览 + MathLive 可视化编辑，存储仍为纯文本（如 -√2）。
 */
const AnswerFormulaInput: React.FC<AnswerFormulaInputProps> = ({
  value = '',
  onChange,
  rows = 3,
}) => {
  const [mode, setMode] = useState<'text' | 'formula'>('formula')
  const mfRef = useRef<MathfieldElement | null>(null)
  const taRef = useRef<any>(null)
  // 避免 MathLive input 与外部 value 循环刷
  const lastEmitted = useRef<string>(value || '')

  // 外部 value 变化时同步到公式框（避免与自身 input 循环）
  useEffect(() => {
    if (mode !== 'formula') {
      lastEmitted.current = value || ''
      return
    }
    const el = mfRef.current
    if (!el) return
    if ((value || '') === lastEmitted.current) return
    lastEmitted.current = value || ''
    const latex = plainToLatex(value || '')
    if (el.value !== latex) el.value = latex
  }, [value, mode])

  useEffect(() => {
    if (mode !== 'formula') return
    const el = mfRef.current
    if (!el) return
    // 切入公式模式时灌入当前值
    el.value = plainToLatex(value || '')
    lastEmitted.current = value || ''
    const onInput = () => {
      const plain = latexToPlain(el.value || '')
      lastEmitted.current = plain
      onChange?.(plain)
    }
    el.addEventListener('input', onInput)
    return () => el.removeEventListener('input', onInput)
    // 仅随 mode 重绑；value/onChange 用 ref 语义由 lastEmitted 协调
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode])

  const insertAtCursor = (snippet: string) => {
    const el = taRef.current?.resizableTextArea?.textArea as HTMLTextAreaElement | undefined
      || taRef.current?.input as HTMLTextAreaElement | undefined
    if (!el || mode !== 'text') {
      onChange?.((value || '') + snippet)
      return
    }
    const start = el.selectionStart ?? (value || '').length
    const end = el.selectionEnd ?? start
    const next = (value || '').slice(0, start) + snippet + (value || '').slice(end)
    onChange?.(next)
    requestAnimationFrame(() => {
      el.focus()
      const pos = start + snippet.length
      el.setSelectionRange(pos, pos)
    })
  }

  return (
    <div>
      <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <Radio.Group
          size="small"
          value={mode}
          onChange={(e) => setMode(e.target.value)}
          optionType="button"
          buttonStyle="solid"
          options={[
            { label: '公式编辑', value: 'formula' },
            { label: '文本编辑', value: 'text' },
          ]}
        />
        {mode === 'text' && (
          <Space size={4} wrap>
            <Button size="small" onClick={() => insertAtCursor('√')}>√</Button>
            <Button size="small" onClick={() => insertAtCursor('1/2')}>分数</Button>
            <Button size="small" onClick={() => insertAtCursor('≤')}>≤</Button>
            <Button size="small" onClick={() => insertAtCursor('≥')}>≥</Button>
            <Button size="small" onClick={() => insertAtCursor('°')}>°</Button>
            <Button size="small" onClick={() => insertAtCursor('π')}>π</Button>
            <Button size="small" onClick={() => insertAtCursor('²')}>x²</Button>
          </Space>
        )}
      </div>

      {mode === 'formula' ? (
        <math-field
          ref={mfRef as any}
          style={{
            display: 'block',
            width: '100%',
            minHeight: 56,
            fontSize: 20,
            padding: '8px 10px',
            border: '1px solid #d9d9d9',
            borderRadius: 6,
            background: '#fff',
          }}
          virtual-keyboard-mode="manual"
        >
          {plainToLatex(value || '')}
        </math-field>
      ) : (
        <TextArea
          ref={taRef}
          rows={rows}
          value={value}
          onChange={(e) => {
            lastEmitted.current = e.target.value
            onChange?.(e.target.value)
          }}
          placeholder="可输入 -√2、1/4，或切换到公式编辑"
        />
      )}

      <div
        style={{
          marginTop: 8,
          padding: '8px 12px',
          background: '#fafafa',
          border: '1px solid #f0f0f0',
          borderRadius: 6,
          minHeight: 40,
        }}
      >
        <Text type="secondary" style={{ marginRight: 8 }}>预览</Text>
        <KaTeXPreview text={value || ''} />
      </div>
      <Text type="secondary" style={{ fontSize: 12 }}>
        存储为文本（如 -√2）；预览用公式排版显示根号横线。复杂题可切「文本编辑」。
      </Text>
    </div>
  )
}

export default AnswerFormulaInput

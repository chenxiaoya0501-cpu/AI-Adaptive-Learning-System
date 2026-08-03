import type { CSSProperties, ReactNode } from 'react'

type ImgInfo = { filename: string; wPt: number; hPt: number }

function parseImgPlaceholder(placeholder: string): ImgInfo | null {
  const m = placeholder.match(/\[IMG:([^,\]]+)(?:,([\d.]+),([\d.]+))?\]/)
  if (!m) return null
  return {
    filename: m[1],
    wPt: m[2] ? parseFloat(m[2]) : 0,
    hPt: m[3] ? parseFloat(m[3]) : 0,
  }
}

/** 与后端一致：区分行内公式 / 独立示意图 */
function isBlockImage(info: ImgInfo): boolean {
  const { wPt, hPt } = info
  if (hPt <= 0 && wPt <= 0) return false
  if (hPt > 45) return true
  if (wPt > 80) return true
  if (wPt >= 55 && hPt >= 28) return true
  return false
}

function imgStyle(info: ImgInfo): CSSProperties {
  if (isBlockImage(info)) {
    const maxH = 150
    const maxW = 320
    let scale = 1.25
    if (info.hPt > 0) scale = Math.min(scale, maxH / info.hPt)
    if (info.wPt > 0) scale = Math.min(scale, maxW / info.wPt)
    return {
      display: 'block',
      margin: '6px 0',
      maxWidth: '100%',
      height: info.hPt > 0 ? info.hPt * scale : maxH,
      width: info.wPt > 0 ? info.wPt * scale : maxW,
    }
  }
  if (info.hPt > 0 && info.wPt > 0) {
    let scale = 1.5
    if (info.hPt * scale > 30) scale = 30 / info.hPt
    return {
      verticalAlign: 'middle',
      margin: '0 3px',
      height: info.hPt * scale,
      width: info.wPt * scale,
    }
  }
  return { verticalAlign: 'middle', margin: '0 3px', maxHeight: 28 }
}

/** 将题干中的 [IMG:filename,W,H] 或已展开的 <img> 渲染出来 */
export function RichQuestionContent({
  text,
  paperId,
}: {
  text?: string | null
  paperId?: number | null
}) {
  if (!text) return null

  // 后端已展开为 <img class="rich-q-img--..."> 时直接按 HTML 展示
  if (text.includes('<img')) {
    return (
      <div
        className="rich-q-content"
        dangerouslySetInnerHTML={{ __html: text.replace(/\n/g, '<br/>') }}
      />
    )
  }

  const parts = text.split(/(\[IMG:[^\]]+\])/g)
  return (
    <div className="rich-q-content">
      {parts.map((part, idx) => {
        const info = parseImgPlaceholder(part)
        if (info && paperId) {
          const url = `/uploads/papers/paper_${paperId}_images/${info.filename}`
          const block = isBlockImage(info)
          return (
            <img
              key={idx}
              className={block ? 'rich-q-img rich-q-img--block' : 'rich-q-img rich-q-img--inline'}
              src={url}
              alt={info.filename}
              style={imgStyle(info)}
            />
          )
        }
        if (info) {
          return (
            <span key={idx} className="rich-q-content__missing">
              [图片]
            </span>
          )
        }
        return <span key={idx}>{part}</span>
      })}
    </div>
  )
}

export function normalizeOptions(options: unknown): Array<[string, string]> {
  if (!options) return []
  if (Array.isArray(options)) {
    return options.map((v, i) => {
      const key = String.fromCharCode(65 + i)
      return [key, typeof v === 'string' ? v : String(v ?? '')]
    })
  }
  if (typeof options === 'object') {
    return Object.entries(options as Record<string, unknown>)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([k, v]) => [k, typeof v === 'string' ? v : String(v ?? '')])
  }
  return []
}

/** 题干 + 选择题选项完整展示 */
export function ExamQuestionBody({
  content,
  options,
  paperId,
}: {
  content?: string | null
  options?: unknown
  paperId?: number | null
}): ReactNode {
  const opts = normalizeOptions(options)
  return (
    <div className="exam-q-body">
      <RichQuestionContent text={content} paperId={paperId} />
      {opts.length > 0 ? (
        <ul className="exam-q-options">
          {opts.map(([k, v]) => (
            <li key={k}>
              <span className="exam-q-options__key">{k}.</span>{' '}
              <RichQuestionContent text={v} paperId={paperId} />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

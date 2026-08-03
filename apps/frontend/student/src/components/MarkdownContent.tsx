import type { ReactNode } from 'react'

function inline(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.filter(Boolean).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={index}>{part.slice(2, -2)}</strong>
    }
    return part
  })
}

function isDivider(line: string) {
  const cells = line.trim().replace(/^\||\|$/g, '').split('|')
  return cells.length > 1 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.trim()))
}

function tableCells(line: string) {
  return line.trim().replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim())
}

export function MarkdownContent({ content }: { content: string }) {
  const lines = content.replace(/\r\n/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index].trim()
    if (!line) {
      index += 1
      continue
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/)
    if (heading) {
      const level = Math.min(heading[1].length + 1, 5)
      const Tag = `h${level}` as keyof JSX.IntrinsicElements
      blocks.push(<Tag key={index}>{inline(heading[2])}</Tag>)
      index += 1
      continue
    }

    if (line.includes('|') && index + 1 < lines.length && isDivider(lines[index + 1])) {
      const headers = tableCells(line)
      const rows: string[][] = []
      index += 2
      while (index < lines.length && lines[index].includes('|') && lines[index].trim()) {
        rows.push(tableCells(lines[index]))
        index += 1
      }
      blocks.push(
        <div className="markdown-table-wrap" key={`table-${index}`}>
          <table>
            <thead><tr>{headers.map((cell, cellIndex) => <th key={cellIndex}>{inline(cell)}</th>)}</tr></thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{inline(cell)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>,
      )
      continue
    }

    if (/^[-*]\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^[-*]\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^[-*]\s+/, ''))
        index += 1
      }
      blocks.push(<ul key={`list-${index}`}>{items.map((item, itemIndex) => <li key={itemIndex}>{inline(item)}</li>)}</ul>)
      continue
    }

    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^\d+\.\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^\d+\.\s+/, ''))
        index += 1
      }
      blocks.push(<ol key={`ordered-${index}`}>{items.map((item, itemIndex) => <li key={itemIndex}>{inline(item)}</li>)}</ol>)
      continue
    }

    const paragraph = [line]
    index += 1
    while (
      index < lines.length
      && lines[index].trim()
      && !/^(#{1,6})\s+/.test(lines[index].trim())
      && !/^[-*]\s+/.test(lines[index].trim())
      && !/^\d+\.\s+/.test(lines[index].trim())
      && !(lines[index].includes('|') && index + 1 < lines.length && isDivider(lines[index + 1]))
    ) {
      paragraph.push(lines[index].trim())
      index += 1
    }
    blocks.push(<p key={`paragraph-${index}`}>{inline(paragraph.join(' '))}</p>)
  }

  return <div className="markdown-content">{blocks}</div>
}

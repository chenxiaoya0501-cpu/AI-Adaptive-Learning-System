/**
 * 格式化后端返回的时间。
 * SQLite 的 CURRENT_TIMESTAMP / func.now() 为 UTC，且通常不带时区后缀；
 * 若按本地直接 new Date() 解析，在中国会慢 8 小时。
 */
export function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  const raw = String(value).trim()
  if (!raw) return '-'

  const normalized = raw.includes('T') ? raw : raw.replace(' ', 'T')
  const hasTimezone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(normalized)
  const date = new Date(hasTimezone ? normalized : `${normalized}Z`)

  if (Number.isNaN(date.getTime())) return raw

  return date.toLocaleString('zh-CN', {
    hour12: false,
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

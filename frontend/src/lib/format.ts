export function relativeTime(iso: string): string {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const diff = Date.now() - t
  const sec = Math.floor(diff / 1000)
  if (sec < 60) return '剛剛'
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min} 分鐘前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小時前`
  const day = Math.floor(hr / 24)
  if (day === 1) return '昨天'
  if (day < 7) return `${day} 天前`
  const d = new Date(t)
  const month = d.getMonth() + 1
  const date = d.getDate()
  const now = new Date()
  if (d.getFullYear() === now.getFullYear()) return `${month}/${date}`
  return `${d.getFullYear()}/${month}/${date}`
}

export function truncate(text: string, max = 60): string {
  if (!text) return ''
  if (text.length <= max) return text
  return text.slice(0, max) + '…'
}

export function formatToolResult(r: unknown): string {
  if (r === undefined || r === null) return ''
  if (typeof r === 'string') return r
  try {
    return JSON.stringify(r, null, 2)
  } catch {
    return String(r)
  }
}

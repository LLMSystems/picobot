import type {
  SessionMessage,
  SessionMessageContentBlock,
  ToolCallRef,
} from './types'

function safeJsonStringify(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function tryParseJson(raw: string): unknown {
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

function extractTextFromContent(
  content: string | SessionMessageContentBlock[],
): { text: string; imagePaths: string[]; imageUrls: string[] } {
  if (typeof content === 'string') {
    return { text: content, imagePaths: [], imageUrls: [] }
  }
  if (!Array.isArray(content)) {
    return { text: '', imagePaths: [], imageUrls: [] }
  }
  const texts: string[] = []
  const paths: string[] = []
  const urls: string[] = []
  for (const block of content) {
    if (!block || typeof block !== 'object') continue
    if (block.type === 'text' && typeof block.text === 'string') {
      texts.push(block.text)
    } else if (block.type === 'image') {
      if (typeof block.path === 'string') paths.push(block.path)
      if (typeof block.url === 'string') urls.push(block.url)
    }
  }
  return { text: texts.join('\n'), imagePaths: paths, imageUrls: urls }
}

function formatToolCall(
  call: ToolCallRef,
  toolResults: Map<string, SessionMessage>,
): string {
  const name = call.function?.name ?? 'tool'
  const argsRaw = call.function?.arguments ?? ''
  const parsedArgs = tryParseJson(argsRaw)
  const argsBlock =
    parsedArgs !== null
      ? '```json\n' + safeJsonStringify(parsedArgs) + '\n```'
      : '```\n' + argsRaw + '\n```'

  const result = toolResults.get(call.id)
  let resultBlock = '_(沒有結果)_'
  if (result) {
    const { text } = extractTextFromContent(result.content)
    if (text) {
      const parsed = tryParseJson(text)
      resultBlock =
        parsed !== null
          ? '```json\n' + safeJsonStringify(parsed) + '\n```'
          : '```\n' + text + '\n```'
    }
  }

  return [
    `#### 🔧 Tool: \`${name}\``,
    '',
    '**Arguments:**',
    argsBlock,
    '',
    '**Result:**',
    resultBlock,
  ].join('\n')
}

export function formatMessagesAsMarkdown(
  messages: SessionMessage[],
  title: string,
  sessionId: string,
): string {
  const exportedAt = new Date().toISOString()
  const toolResults = new Map<string, SessionMessage>()
  for (const m of messages) {
    if (m.role === 'tool' && m.tool_call_id) {
      toolResults.set(m.tool_call_id, m)
    }
  }

  const lines: string[] = []
  lines.push(`# ${title || 'Picobot Session'}`)
  lines.push('')
  lines.push(`> Session ID: \`${sessionId}\`  `)
  lines.push(`> Exported: ${exportedAt}`)
  lines.push('')
  lines.push('---')
  lines.push('')

  for (const m of messages) {
    if (m.role === 'user') {
      const { text, imagePaths, imageUrls } = extractTextFromContent(m.content)
      const created = m.created_at ?? ''
      lines.push(`## 👤 User${created ? ` · ${created}` : ''}`)
      lines.push('')
      if (text) {
        lines.push(text)
        lines.push('')
      }
      const allImages = [
        ...(m.images?.map((img) => img.path ?? img.url ?? '') ?? []),
        ...imagePaths,
        ...imageUrls,
      ].filter((s) => s.length > 0)
      if (allImages.length > 0) {
        lines.push('**Images:**')
        for (const p of allImages) lines.push(`- \`${p}\``)
        lines.push('')
      }
      lines.push('---')
      lines.push('')
    } else if (m.role === 'assistant') {
      const created = m.created_at ?? ''
      lines.push(`## 🤖 Assistant${created ? ` · ${created}` : ''}`)
      lines.push('')
      const textContent =
        typeof m.content === 'string'
          ? m.content
          : extractTextFromContent(m.content).text
      if (textContent) {
        lines.push(textContent)
        lines.push('')
      }
      if (m.tool_calls && m.tool_calls.length > 0) {
        for (const tc of m.tool_calls) {
          lines.push(formatToolCall(tc, toolResults))
          lines.push('')
        }
      }
      lines.push('---')
      lines.push('')
    }
  }

  return lines.join('\n').replace(/\n{3,}/g, '\n\n')
}

export function formatMessagesAsJson(
  messages: SessionMessage[],
  title: string,
  sessionId: string,
): string {
  const payload = {
    session_id: sessionId,
    title,
    exported_at: new Date().toISOString(),
    messages,
  }
  return JSON.stringify(payload, null, 2)
}

export function sanitizeFilename(name: string): string {
  const cleaned = name
    .trim()
    .replace(/[\\/:*?"<>|]+/g, '_')
    .replace(/\s+/g, '_')
    .slice(0, 60)
  return cleaned || 'picobot-session'
}

export function downloadAsFile(
  filename: string,
  content: string,
  mime: string,
): void {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

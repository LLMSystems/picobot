export interface SseEvent {
  event: string
  data: string
  id?: string
}

export async function* parseSse(
  stream: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<SseEvent> {
  const decoder = new TextDecoder()
  const reader = stream.getReader()
  let buffer = ''

  try {
    while (true) {
      if (signal?.aborted) return
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      let idx: number
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const raw = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        const evt = parseFrame(raw)
        if (evt) yield evt
      }
    }
    const tail = buffer.trim()
    if (tail) {
      const evt = parseFrame(tail)
      if (evt) yield evt
    }
  } finally {
    try {
      reader.releaseLock()
    } catch {
      // ignore
    }
  }
}

function parseFrame(raw: string): SseEvent | null {
  if (!raw.trim()) return null
  let event = 'message'
  const dataLines: string[] = []
  let id: string | undefined
  for (const rawLine of raw.split('\n')) {
    const line = rawLine.replace(/\r$/, '')
    if (!line || line.startsWith(':')) continue
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).replace(/^ /, ''))
    } else if (line.startsWith('id:')) {
      id = line.slice(3).trim()
    }
  }
  return { event, data: dataLines.join('\n'), id }
}

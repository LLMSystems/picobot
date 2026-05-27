// One-line summary of a tool call's outcome — surfaced in the collapsed
// tool card header so users don't need to expand to see what happened.

type Args = Record<string, unknown>
type Summarizer = (args: Args, result: unknown) => string | null

function firstLine(s: string, max = 60): string {
  const line = (s.split('\n').find((l) => l.trim() !== '') ?? '').trim()
  return line.length > max ? line.slice(0, max) + '…' : line
}

function asString(v: unknown): string | null {
  return typeof v === 'string' ? v : null
}

function asNumber(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function arrayLen(v: unknown): number | null {
  return Array.isArray(v) ? v.length : null
}

function pick<T = unknown>(obj: unknown, key: string): T | undefined {
  if (obj && typeof obj === 'object' && key in obj) {
    return (obj as Record<string, T>)[key]
  }
  return undefined
}

function baseName(path: string): string {
  const idx = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'))
  return idx >= 0 ? path.slice(idx + 1) : path
}

const SUMMARIZERS: Record<string, Summarizer> = {
  read_file: (args, result) => {
    const path = asString(args.path)
    if (typeof result === 'string') {
      const lines = result.split('\n').length
      return path ? `${baseName(path)}（${lines} 行）` : `${lines} 行`
    }
    return path ? baseName(path) : null
  },
  write_file: (args) => {
    const p = asString(args.path)
    return p ? `已寫入 ${baseName(p)}` : '已寫入'
  },
  edit_file: (args) => {
    const p = asString(args.path)
    return p ? `已編輯 ${baseName(p)}` : '已編輯'
  },
  list_dir: (args, result) => {
    const entries = pick(result, 'entries')
    const n = arrayLen(entries) ?? arrayLen(result)
    return n !== null ? `${n} 個項目` : null
  },
  glob: (_, result) => {
    const matches = pick(result, 'matches')
    const n = arrayLen(matches) ?? arrayLen(result)
    return n !== null ? `找到 ${n} 個檔案` : null
  },
  grep: (_, result) => {
    const matches = pick(result, 'matches')
    const n = arrayLen(matches) ?? arrayLen(result)
    if (n !== null) return `${n} 個匹配`
    if (typeof result === 'string') {
      const lines = result.split('\n').filter((l) => l.trim() !== '').length
      return `${lines} 個匹配`
    }
    return null
  },
  exec: (args, result) => {
    const cmd = asString(args.command) ?? asString(args.cmd)
    const exit = asNumber(pick(result, 'exit_code')) ?? asNumber(pick(result, 'exitCode'))
    if (cmd) {
      const short = cmd.length > 40 ? cmd.slice(0, 40) + '…' : cmd
      return exit !== null ? `${short}  · exit ${exit}` : short
    }
    if (exit !== null) return `exit ${exit}`
    if (typeof result === 'string') return firstLine(result)
    return null
  },
  spawn: (args, result) => {
    const label = asString(args.label) ?? asString(args.task) ?? asString(pick(result, 'task_id'))
    return label ? `派發：${label}` : '已派發子代理'
  },
  list_subagents: (_, result) => {
    const items = pick(result, 'items')
    const n = arrayLen(items) ?? arrayLen(result)
    return n !== null ? `${n} 個子代理` : null
  },
  subagent_status: (args) => {
    const id = asString(args.task_id) ?? asString(args.taskId)
    return id ? id : null
  },
  subagent_wait: (args) => {
    const id = asString(args.task_id) ?? asString(args.taskId)
    return id ? `已等待 ${id}` : null
  },
  tavily_search: (args, result) => {
    const q = asString(args.query)
    const results = pick(result, 'results')
    const n = arrayLen(results) ?? arrayLen(result)
    if (q && n !== null) return `「${firstLine(q, 30)}」 · ${n} 個結果`
    if (q) return `「${firstLine(q, 30)}」`
    if (n !== null) return `${n} 個結果`
    return null
  },
  read_pdf: (args) => {
    const p = asString(args.path)
    return p ? baseName(p) : null
  },
  read_docx: (args) => {
    const p = asString(args.path)
    return p ? baseName(p) : null
  },
  read_xlsx: (args) => {
    const p = asString(args.path)
    return p ? baseName(p) : null
  },
}

function genericFallback(result: unknown): string | null {
  if (result === null || result === undefined) return null
  if (typeof result === 'string') return firstLine(result)
  if (typeof result === 'number' || typeof result === 'boolean') {
    return String(result)
  }
  if (Array.isArray(result)) return `${result.length} 個項目`
  try {
    return firstLine(JSON.stringify(result))
  } catch {
    return null
  }
}

/**
 * Build a short summary line for a successful tool call.
 * Returns `null` when nothing meaningful can be derived.
 */
export function toolSummary(
  name: string,
  args: Record<string, unknown> | undefined,
  result: unknown,
): string | null {
  const fn = SUMMARIZERS[name]
  const fromTool = fn ? fn(args ?? {}, result) : null
  return fromTool ?? genericFallback(result)
}

/**
 * Build a short error blurb for a failed tool call.
 * Pulls from common error shapes: string error, { error }, { message }, raw result.
 */
export function toolErrorSummary(result: unknown): string | null {
  if (typeof result === 'string') return firstLine(result)
  const err = pick(result, 'error') ?? pick(result, 'message')
  if (typeof err === 'string') return firstLine(err)
  if (result === null || result === undefined) return null
  try {
    return firstLine(JSON.stringify(result))
  } catch {
    return null
  }
}

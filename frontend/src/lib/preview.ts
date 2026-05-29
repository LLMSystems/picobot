export type PreviewKind = 'image' | 'svg' | 'pdf' | 'html' | 'text'

const IMAGE_EXTS = new Set([
  'png',
  'jpg',
  'jpeg',
  'gif',
  'webp',
  'bmp',
  'ico',
  'avif',
])

export function detectPreviewKind(path: string | null | undefined): PreviewKind {
  if (!path) return 'text'
  const base = path.toLowerCase().split('/').pop() ?? ''
  const dot = base.lastIndexOf('.')
  if (dot < 0) return 'text'
  const ext = base.slice(dot + 1)
  if (ext === 'svg') return 'svg'
  if (ext === 'pdf') return 'pdf'
  if (ext === 'html' || ext === 'htm') return 'html'
  if (IMAGE_EXTS.has(ext)) return 'image'
  return 'text'
}

const EXT_TO_LANG: Record<string, string> = {
  py: 'python',
  js: 'javascript',
  mjs: 'javascript',
  cjs: 'javascript',
  jsx: 'javascript',
  ts: 'typescript',
  tsx: 'typescript',
  vue: 'vue',
  html: 'html',
  htm: 'html',
  xml: 'xml',
  svg: 'xml',
  css: 'css',
  scss: 'scss',
  less: 'less',
  json: 'json',
  yaml: 'yaml',
  yml: 'yaml',
  toml: 'ini',
  ini: 'ini',
  sh: 'bash',
  bash: 'bash',
  zsh: 'bash',
  rs: 'rust',
  go: 'go',
  java: 'java',
  kt: 'kotlin',
  cpp: 'cpp',
  cc: 'cpp',
  cxx: 'cpp',
  hpp: 'cpp',
  h: 'c',
  c: 'c',
  rb: 'ruby',
  php: 'php',
  sql: 'sql',
  swift: 'swift',
  dockerfile: 'dockerfile',
  makefile: 'makefile',
  md: 'markdown',
  markdown: 'markdown',
  txt: 'text',
  log: 'text',
}

const LANG_LABELS: Record<string, string> = {
  python: 'Python',
  javascript: 'JavaScript',
  typescript: 'TypeScript',
  xml: 'XML',
  html: 'HTML',
  vue: 'Vue',
  css: 'CSS',
  scss: 'SCSS',
  less: 'Less',
  json: 'JSON',
  yaml: 'YAML',
  ini: 'INI',
  bash: 'Shell',
  rust: 'Rust',
  go: 'Go',
  java: 'Java',
  kotlin: 'Kotlin',
  cpp: 'C++',
  c: 'C',
  ruby: 'Ruby',
  php: 'PHP',
  sql: 'SQL',
  swift: 'Swift',
  dockerfile: 'Dockerfile',
  makefile: 'Makefile',
  markdown: 'Markdown',
  text: 'Text',
}

export function detectLanguage(path: string | null | undefined): string | null {
  if (!path) return null
  const lower = path.toLowerCase()
  const base = lower.split('/').pop() ?? lower
  if (base === 'dockerfile') return 'dockerfile'
  if (base === 'makefile') return 'makefile'
  const ext = base.includes('.') ? (base.split('.').pop() ?? '') : ''
  if (!ext) return null
  return EXT_TO_LANG[ext] ?? null
}

export function languageLabel(lang: string | null | undefined): string | null {
  if (!lang) return null
  return LANG_LABELS[lang] ?? lang.toUpperCase()
}

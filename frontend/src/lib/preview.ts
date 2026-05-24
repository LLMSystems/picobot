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

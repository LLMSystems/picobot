import { computed, onBeforeUnmount, ref } from 'vue'
import { toast } from 'vue-sonner'
import { api } from '@/lib/api'
import { ApiError } from '@/lib/errors'
import { useWorkspaceStore } from '@/stores/workspace'
import type { ChatImageInput } from '@/lib/types'

export const MAX_IMAGES_PER_MESSAGE = 4
export const MAX_IMAGE_BYTES = 10 * 1024 * 1024
export const MAX_FILE_BYTES = 50 * 1024 * 1024
export const UPLOAD_SUBDIR = 'uploads/chat'

export type AttachmentStatus = 'uploading' | 'ready' | 'error'
export type AttachmentKind = 'image' | 'file'

export interface ImageAttachment {
  kind: 'image'
  id: string
  file: File
  previewUrl: string
  status: AttachmentStatus
  path?: string
  error?: string
}

export interface FileAttachment {
  kind: 'file'
  id: string
  file: File
  status: AttachmentStatus
  path?: string
  error?: string
}

export type Attachment = ImageAttachment | FileAttachment

// Accepted MIME types for non-image file attachments
export const ACCEPTED_FILE_TYPES = [
  'application/pdf',
  'text/plain',
  'text/markdown',
  'text/csv',
  'text/html',
  'text/xml',
  'application/json',
  'application/xml',
]

export const ACCEPTED_FILE_EXTENSIONS = [
  '.pdf', '.txt', '.md', '.markdown', '.csv',
  '.html', '.htm', '.xml', '.json', '.log',
  '.yaml', '.yml', '.toml', '.ini', '.conf',
  '.py', '.js', '.ts', '.jsx', '.tsx', '.vue',
  '.rs', '.go', '.java', '.kt', '.cpp', '.c', '.h',
  '.rb', '.php', '.sh', '.bash',
]

function isImageFile(file: File): boolean {
  return file.type.startsWith('image/')
}

let attachmentIdSeq = 0
function newId(): string {
  attachmentIdSeq += 1
  return `att-${Date.now()}-${attachmentIdSeq}`
}

function describeUploadError(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case 'WORKSPACE_NOT_AVAILABLE':
        return '此 session 沒有啟用 workspace'
      case 'WORKSPACE_PATH_INVALID':
        return '路徑不合法'
      default:
        return err.message
    }
  }
  return err instanceof Error ? err.message : '上傳失敗'
}

async function ensureUploadDir(sessionId: string): Promise<void> {
  await api.createWorkspaceDirectory(sessionId, { path: UPLOAD_SUBDIR })
}

function uniqueFileName(file: File): string {
  const dot = file.name.lastIndexOf('.')
  const stem = dot > 0 ? file.name.slice(0, dot) : file.name || 'file'
  const ext =
    dot > 0
      ? file.name.slice(dot).toLowerCase()
      : file.type === 'image/png'
        ? '.png'
        : file.type === 'image/jpeg'
          ? '.jpg'
          : file.type === 'image/webp'
            ? '.webp'
            : file.type === 'image/gif'
              ? '.gif'
              : ''
  const safe = stem.replace(/[^\w.-]+/g, '_').slice(0, 60) || 'file'
  return `${Date.now()}-${Math.random().toString(36).slice(2, 6)}-${safe}${ext}`
}

export function useImageAttachments(
  getSessionId: () => string | null,
  onFileReady?: (path: string) => void,
  onFileRemoved?: (path: string) => void,
) {
  const attachments = ref<Attachment[]>([])

  const imageAttachments = computed(
    () => attachments.value.filter((a): a is ImageAttachment => a.kind === 'image'),
  )
  const fileAttachments = computed(
    () => attachments.value.filter((a): a is FileAttachment => a.kind === 'file'),
  )

  const canAddMoreImages = computed(
    () => imageAttachments.value.length < MAX_IMAGES_PER_MESSAGE,
  )
  const hasUploading = computed(() =>
    attachments.value.some((a) => a.status === 'uploading'),
  )
  const hasReady = computed(() =>
    attachments.value.some((a) => a.status === 'ready'),
  )

  function revokePreview(att: Attachment) {
    if (att.kind === 'image') {
      try {
        URL.revokeObjectURL(att.previewUrl)
      } catch {
        // ignore
      }
    }
  }

  function findAtt(id: string): Attachment | undefined {
    return attachments.value.find((a) => a.id === id)
  }

  async function uploadOne(attId: string, file: File, sessionId: string, isImage: boolean) {
    const renamed = new File([file], uniqueFileName(file), { type: file.type })
    try {
      await ensureUploadDir(sessionId)
      const resp = await api.uploadWorkspaceFiles(
        sessionId,
        { path: UPLOAD_SUBDIR, overwrite: false },
        [renamed],
      )
      const target = findAtt(attId)
      if (!target) return
      const uploaded = resp.uploaded[0]
      if (!uploaded) {
        target.status = 'error'
        ;(target as { error?: string }).error = '上傳失敗'
        return
      }
      target.path = uploaded.path
      target.status = 'ready'
      void useWorkspaceStore().refreshPaths([uploaded.path])
      if (!isImage && onFileReady) {
        onFileReady(uploaded.path)
      }
    } catch (err) {
      const target = findAtt(attId)
      if (!target) return
      target.status = 'error'
      ;(target as { error?: string }).error = describeUploadError(err)
    }
  }

  function addFiles(files: File[]) {
    const sessionId = getSessionId()
    if (!sessionId) {
      toast.error('請先選擇對話')
      return
    }

    const imageFiles: File[] = []
    const docFiles: File[] = []
    let rejectedTooLarge = 0

    for (const f of files) {
      if (f.type.startsWith('image/')) {
        if (f.size > MAX_IMAGE_BYTES) {
          rejectedTooLarge += 1
          continue
        }
        imageFiles.push(f)
      } else {
        if (f.size > MAX_FILE_BYTES) {
          rejectedTooLarge += 1
          continue
        }
        docFiles.push(f)
      }
    }

    if (rejectedTooLarge > 0) {
      toast.error(`已忽略 ${rejectedTooLarge} 個超過大小限制的檔案`)
    }

    // Handle image files
    const available = MAX_IMAGES_PER_MESSAGE - imageAttachments.value.length
    if (imageFiles.length > 0 && available <= 0) {
      toast.error(`一則訊息最多 ${MAX_IMAGES_PER_MESSAGE} 張圖片`)
    } else {
      const accepted = imageFiles.slice(0, available)
      if (imageFiles.length > available && available > 0) {
        toast.warning(`已超過圖片上限 ${MAX_IMAGES_PER_MESSAGE} 張，僅加入前 ${available} 張`)
      }
      for (const file of accepted) {
        const att: ImageAttachment = {
          kind: 'image',
          id: newId(),
          file,
          previewUrl: URL.createObjectURL(file),
          status: 'uploading',
        }
        attachments.value.push(att)
        void uploadOne(att.id, file, sessionId, true)
      }
    }

    // Handle document files
    for (const file of docFiles) {
      const att: FileAttachment = {
        kind: 'file',
        id: newId(),
        file,
        status: 'uploading',
      }
      attachments.value.push(att)
      void uploadOne(att.id, file, sessionId, false)
    }
  }

  function remove(id: string) {
    const idx = attachments.value.findIndex((a) => a.id === id)
    if (idx < 0) return
    const [att] = attachments.value.splice(idx, 1)
    if (!att) return
    revokePreview(att)
    if (att.kind === 'file' && att.path && att.status === 'ready' && onFileRemoved) {
      onFileRemoved(att.path)
    }
  }

  function retry(id: string) {
    const sessionId = getSessionId()
    if (!sessionId) return
    const att = findAtt(id)
    if (!att || att.status !== 'error') return
    att.status = 'uploading'
    ;(att as { error?: string }).error = undefined
    void uploadOne(att.id, att.file, sessionId, att.kind === 'image')
  }

  function clearAll() {
    for (const att of attachments.value) revokePreview(att)
    attachments.value = []
  }

  function toImages(): ChatImageInput[] {
    return imageAttachments.value
      .filter((a) => a.status === 'ready' && a.path)
      .map((a) => ({ path: a.path! }))
  }

  function handlePaste(event: ClipboardEvent): boolean {
    const items = event.clipboardData?.items
    if (!items) return false
    const files: File[] = []
    for (const item of items) {
      if (item.kind === 'file') {
        const file = item.getAsFile()
        if (file && file.type.startsWith('image/')) files.push(file)
      }
    }
    if (files.length === 0) return false
    event.preventDefault()
    addFiles(files)
    return true
  }

  function handleDrop(event: DragEvent): boolean {
    const files = event.dataTransfer?.files
    if (!files || files.length === 0) return false
    const list = Array.from(files)
    const accepted = list.filter(
      (f) => f.type.startsWith('image/') || !isImageFile(f),
    )
    if (accepted.length === 0) return false
    event.preventDefault()
    addFiles(accepted)
    return true
  }

  onBeforeUnmount(() => {
    for (const att of attachments.value) revokePreview(att)
  })

  return {
    attachments,
    imageAttachments,
    fileAttachments,
    canAddMoreImages,
    // keep old name as alias for compatibility
    canAddMore: canAddMoreImages,
    hasUploading,
    hasReady,
    addFiles,
    remove,
    retry,
    clearAll,
    toImages,
    handlePaste,
    handleDrop,
  }
}

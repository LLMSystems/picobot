import { computed, onBeforeUnmount, ref } from 'vue'
import { toast } from 'vue-sonner'
import { api } from '@/lib/api'
import { ApiError } from '@/lib/errors'
import type { ChatImageInput } from '@/lib/types'

export const MAX_IMAGES_PER_MESSAGE = 4
export const MAX_IMAGE_BYTES = 10 * 1024 * 1024
export const UPLOAD_SUBDIR = 'uploads/chat'

export type AttachmentStatus = 'uploading' | 'ready' | 'error'

export interface ImageAttachment {
  id: string
  file: File
  previewUrl: string
  status: AttachmentStatus
  path?: string
  error?: string
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

const ensuredDirs = new Set<string>()

async function ensureUploadDir(sessionId: string): Promise<void> {
  const key = `${sessionId}:${UPLOAD_SUBDIR}`
  if (ensuredDirs.has(key)) return
  await api.createWorkspaceDirectory(sessionId, { path: UPLOAD_SUBDIR })
  ensuredDirs.add(key)
}

function uniqueFileName(file: File): string {
  const dot = file.name.lastIndexOf('.')
  const stem = dot > 0 ? file.name.slice(0, dot) : file.name || 'image'
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
  const safe = stem.replace(/[^\w.-]+/g, '_').slice(0, 60) || 'image'
  return `${Date.now()}-${Math.random().toString(36).slice(2, 6)}-${safe}${ext}`
}

export function useImageAttachments(getSessionId: () => string | null) {
  const attachments = ref<ImageAttachment[]>([])

  const canAddMore = computed(
    () => attachments.value.length < MAX_IMAGES_PER_MESSAGE,
  )
  const hasUploading = computed(() =>
    attachments.value.some((a) => a.status === 'uploading'),
  )
  const hasReady = computed(() =>
    attachments.value.some((a) => a.status === 'ready'),
  )

  function revokePreview(att: ImageAttachment) {
    try {
      URL.revokeObjectURL(att.previewUrl)
    } catch {
      // ignore
    }
  }

  function findAtt(id: string): ImageAttachment | undefined {
    return attachments.value.find((a) => a.id === id)
  }

  async function uploadOne(attId: string, file: File, sessionId: string) {
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
        target.error = '上傳失敗'
        return
      }
      target.path = uploaded.path
      target.status = 'ready'
    } catch (err) {
      const target = findAtt(attId)
      if (!target) return
      target.status = 'error'
      target.error = describeUploadError(err)
    }
  }

  function addFiles(files: File[]) {
    const sessionId = getSessionId()
    if (!sessionId) {
      toast.error('請先選擇對話')
      return
    }

    const imageFiles: File[] = []
    let rejectedNonImage = 0
    let rejectedTooLarge = 0

    for (const f of files) {
      if (!f.type.startsWith('image/')) {
        rejectedNonImage += 1
        continue
      }
      if (f.size > MAX_IMAGE_BYTES) {
        rejectedTooLarge += 1
        continue
      }
      imageFiles.push(f)
    }

    if (rejectedNonImage > 0) {
      toast.error(`已忽略 ${rejectedNonImage} 個非圖片檔案`)
    }
    if (rejectedTooLarge > 0) {
      toast.error(`已忽略 ${rejectedTooLarge} 個超過 10 MiB 的圖片`)
    }
    if (imageFiles.length === 0) return

    const available = MAX_IMAGES_PER_MESSAGE - attachments.value.length
    if (available <= 0) {
      toast.error(`一則訊息最多 ${MAX_IMAGES_PER_MESSAGE} 張圖片`)
      return
    }
    const accepted = imageFiles.slice(0, available)
    if (imageFiles.length > available) {
      toast.warning(
        `已超過上限 ${MAX_IMAGES_PER_MESSAGE} 張，僅加入前 ${available} 張`,
      )
    }

    for (const file of accepted) {
      const att: ImageAttachment = {
        id: newId(),
        file,
        previewUrl: URL.createObjectURL(file),
        status: 'uploading',
      }
      attachments.value.push(att)
      void uploadOne(att.id, file, sessionId)
    }
  }

  function remove(id: string) {
    const idx = attachments.value.findIndex((a) => a.id === id)
    if (idx < 0) return
    const [att] = attachments.value.splice(idx, 1)
    if (att) revokePreview(att)
  }

  function retry(id: string) {
    const sessionId = getSessionId()
    if (!sessionId) return
    const att = findAtt(id)
    if (!att || att.status !== 'error') return
    att.status = 'uploading'
    att.error = undefined
    void uploadOne(att.id, att.file, sessionId)
  }

  function clearAll() {
    for (const att of attachments.value) revokePreview(att)
    attachments.value = []
  }

  function toImages(): ChatImageInput[] {
    return attachments.value
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
    const list = Array.from(files).filter((f) => f.type.startsWith('image/'))
    if (list.length === 0) return false
    event.preventDefault()
    addFiles(list)
    return true
  }

  onBeforeUnmount(() => {
    for (const att of attachments.value) revokePreview(att)
  })

  return {
    attachments,
    canAddMore,
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

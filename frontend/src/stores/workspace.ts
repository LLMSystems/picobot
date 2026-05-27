import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { toast } from 'vue-sonner'
import { api } from '@/lib/api'
import { ApiError } from '@/lib/errors'
import { detectPreviewKind } from '@/lib/preview'
import { useComposerBus } from '@/composables/useComposerBus'
import type {
  WorkspaceEntryDTO,
  WorkspaceFileResponse,
  WorkspaceUploadResponse,
} from '@/lib/types'

const VISIBLE_STORAGE_KEY = 'picobot:workspace:visible'
const TAB_STORAGE_KEY = 'picobot:workspace:tab'

export type WorkspaceTab = 'files' | 'browser' | 'agents'

function loadTab(): WorkspaceTab {
  try {
    const v = localStorage.getItem(TAB_STORAGE_KEY)
    if (v === 'files' || v === 'browser' || v === 'agents') return v
  } catch {
    // ignore
  }
  return 'files'
}

export const MAX_UPLOAD_FILE_BYTES = 10 * 1024 * 1024
export const MAX_UPLOAD_FILES_PER_REQUEST = 20

function formatBytes(n: number): string {
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MiB`
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KiB`
  return `${n} B`
}

function describeDeleteError(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case 'WORKSPACE_NOT_AVAILABLE':
        return '此 session 沒有啟用 workspace'
      case 'WORKSPACE_PATH_INVALID':
        return '路徑不合法'
      case 'WORKSPACE_FILE_NOT_FOUND':
        return '檔案已不存在'
      case 'WORKSPACE_NOT_A_FILE':
        return '無法刪除資料夾，只能刪除檔案'
      default:
        return err.message
    }
  }
  return err instanceof Error ? err.message : '刪除失敗'
}

function describeMoveError(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case 'WORKSPACE_MOVE_INTO_SELF':
        return '不能搬到自己底下'
      case 'WORKSPACE_MOVE_SAME_PATH':
        return '來源和目標相同'
      case 'WORKSPACE_MOVE_DESTINATION_IS_DIRECTORY':
        return '目標位置已是資料夾，無法合併'
      case 'WORKSPACE_FILE_NOT_FOUND':
        return '來源已不存在'
      case 'WORKSPACE_PATH_INVALID':
        return '路徑不合法'
      default:
        return err.message
    }
  }
  return err instanceof Error ? err.message : '操作失敗'
}

function describeUploadError(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case 'WORKSPACE_NOT_AVAILABLE':
        return '此 session 沒有啟用 workspace'
      case 'WORKSPACE_PATH_INVALID':
        return '路徑不合法'
      case 'WORKSPACE_DIRECTORY_NOT_FOUND':
        return '目標資料夾不存在'
      case 'WORKSPACE_NOT_A_DIRECTORY':
        return '目標路徑不是資料夾'
      case 'WORKSPACE_UPLOAD_NO_FILES':
        return '沒有選擇檔案'
      case 'WORKSPACE_UPLOAD_FILENAME_INVALID':
        return '檔名含有非法字元'
      case 'WORKSPACE_UPLOAD_FILE_TOO_LARGE':
        return '檔案大小超過後端限制'
      case 'WORKSPACE_UPLOAD_TOO_MANY_FILES':
        return '檔案數量超過後端限制'
      default:
        return err.message
    }
  }
  return err instanceof Error ? err.message : '上傳失敗'
}

export type SortMode = 'updated' | 'name'

export type WorkspaceLoadState =
  | 'idle'
  | 'loading'
  | 'unavailable'
  | 'empty'
  | 'ready'
  | 'error'

interface DirState {
  childrenLoaded: boolean
  loading: boolean
  truncated: boolean
}

function loadVisible(): boolean {
  try {
    const v = localStorage.getItem(VISIBLE_STORAGE_KEY)
    if (v === '1') return true
    if (v === '0') return false
  } catch {
    // ignore
  }
  return true
}

export const useWorkspaceStore = defineStore('workspace', () => {
  const sessionId = ref<string | null>(null)
  const entries = ref<Map<string, WorkspaceEntryDTO>>(new Map())
  const dirState = ref<Map<string, DirState>>(new Map())
  const expanded = ref<Set<string>>(new Set())
  const selectedPath = ref<string | null>(null)
  const fileContent = ref<WorkspaceFileResponse | null>(null)
  const fileError = ref<ApiError | null>(null)
  const loadingFile = ref(false)
  const loadState = ref<WorkspaceLoadState>('idle')
  const lastSyncedAt = ref(0)
  const sortMode = ref<SortMode>('updated')
  const visible = ref(loadVisible())
  const activeTab = ref<WorkspaceTab>(loadTab())
  const draggingPath = ref<string | null>(null)
  const pendingMoveConflict = ref<{ src: string; dst: string } | null>(null)
  const uploading = ref(false)
  const uploadConflict = ref<{
    files: File[]
    names: string[]
    target: string
  } | null>(null)
  const pendingRename = ref<{
    path: string
    type: 'file' | 'directory'
    name: string
  } | null>(null)
  const pendingDelete = ref<{ path: string; name: string; type: 'file' | 'directory' } | null>(null)
  const mkdirRequest = ref<{ parent: string } | null>(null)
  const pendingNewFile = ref<{ parent: string } | null>(null)
  const activeDir = ref<string>('.')
  const editMode = ref(false)
  const editContent = ref('')
  const editSaving = ref(false)

  function openMkdir(parent?: string) {
    mkdirRequest.value = { parent: parent ?? targetUploadDir() }
  }

  function closeMkdir() {
    mkdirRequest.value = null
  }

  function openNewFile(parent?: string) {
    pendingNewFile.value = { parent: parent ?? targetUploadDir() }
  }

  function closeNewFile() {
    pendingNewFile.value = null
  }

  function persistVisible() {
    try {
      localStorage.setItem(VISIBLE_STORAGE_KEY, visible.value ? '1' : '0')
    } catch {
      // ignore
    }
  }

  function setVisible(v: boolean) {
    visible.value = v
    persistVisible()
  }

  function toggleVisible() {
    setVisible(!visible.value)
  }

  function setActiveTab(tab: WorkspaceTab) {
    activeTab.value = tab
    try {
      localStorage.setItem(TAB_STORAGE_KEY, tab)
    } catch {
      // ignore
    }
  }

  function focusBrowser() {
    setActiveTab('browser')
    if (!visible.value) setVisible(true)
  }

  function focusAgents() {
    setActiveTab('agents')
    if (!visible.value) setVisible(true)
  }

  function parentOf(path: string): string {
    if (!path || path === '.') return ''
    const i = path.lastIndexOf('/')
    return i < 0 ? '' : path.slice(0, i)
  }

  function reset(): void {
    entries.value = new Map()
    dirState.value = new Map()
    expanded.value = new Set()
    selectedPath.value = null
    fileContent.value = null
    fileError.value = null
    loadingFile.value = false
    loadState.value = 'idle'
    lastSyncedAt.value = 0
    activeDir.value = '.'
  }

  function mergeEntries(list: WorkspaceEntryDTO[]) {
    for (const e of list) {
      entries.value.set(e.path, e)
    }
  }

  function getDir(path: string): DirState {
    let s = dirState.value.get(path)
    if (!s) {
      s = { childrenLoaded: false, loading: false, truncated: false }
      dirState.value.set(path, s)
    }
    return s
  }

  function replaceDirChildren(dir: string, list: WorkspaceEntryDTO[]) {
    const keep: Array<[string, WorkspaceEntryDTO]> = []
    for (const [k, v] of entries.value) {
      if (parentOf(k) !== dir) keep.push([k, v])
    }
    const next = new Map(keep)
    for (const e of list) next.set(e.path, e)
    entries.value = next
  }

  async function bind(id: string | null) {
    sessionId.value = id
    reset()
    if (!id) return
    await refreshTree({ path: '.' })
  }

  async function refreshTree(opts: { path?: string } = {}) {
    const id = sessionId.value
    if (!id) return
    const path = opts.path ?? '.'
    const dirKey = path === '.' ? '' : path

    const s = getDir(dirKey)
    s.loading = true
    if (path === '.') loadState.value = 'loading'

    try {
      const resp = await api.listWorkspaceTree(id, { path, recursive: false })
      if (sessionId.value !== id) return
      replaceDirChildren(dirKey, resp.entries)
      s.childrenLoaded = true
      s.truncated = resp.truncated
      lastSyncedAt.value = Date.now()
      if (path === '.') {
        loadState.value = resp.entries.length === 0 ? 'empty' : 'ready'
      }
    } catch (err) {
      if (sessionId.value !== id) return
      if (err instanceof ApiError && err.code === 'WORKSPACE_NOT_AVAILABLE') {
        if (path === '.') loadState.value = 'unavailable'
      } else if (path === '.') {
        loadState.value = 'error'
      }
    } finally {
      s.loading = false
    }
  }

  async function refreshExpanded() {
    const id = sessionId.value
    if (!id) return
    const dirs: string[] = ['']
    for (const path of expanded.value) dirs.push(path)
    await Promise.all(
      dirs.map((d) => refreshTree({ path: d === '' ? '.' : d })),
    )
    if (selectedPath.value) await loadFile(selectedPath.value)
  }

  async function refreshPaths(paths: string[]) {
    const id = sessionId.value
    if (!id) return
    const dirsToRefresh = new Set<string>()
    for (const p of paths) {
      const parent = parentOf(p)
      if (parent === '' || expanded.value.has(parent)) {
        dirsToRefresh.add(parent)
      }
    }
    await Promise.all(
      [...dirsToRefresh].map((d) => refreshTree({ path: d === '' ? '.' : d })),
    )
    if (selectedPath.value && paths.includes(selectedPath.value)) {
      await loadFile(selectedPath.value)
    }
  }

  async function expand(path: string) {
    if (expanded.value.has(path)) return
    expanded.value = new Set([...expanded.value, path])
    const s = getDir(path)
    if (!s.childrenLoaded && !s.loading) {
      await refreshTree({ path })
    }
  }

  function collapse(path: string) {
    if (!expanded.value.has(path)) return
    const next = new Set(expanded.value)
    next.delete(path)
    expanded.value = next
  }

  async function toggleExpand(path: string) {
    if (expanded.value.has(path)) collapse(path)
    else {
      activeDir.value = path
      await expand(path)
    }
  }

  async function select(path: string | null) {
    editMode.value = false
    editContent.value = ''
    selectedPath.value = path
    fileContent.value = null
    fileError.value = null
    if (!path) return
    const kind = detectPreviewKind(path)
    if (kind !== 'text' && kind !== 'html') return
    await loadFile(path)
  }

  async function loadFile(path: string, opts: { offset?: number; limit?: number } = {}) {
    const id = sessionId.value
    if (!id) return
    loadingFile.value = true
    fileError.value = null
    try {
      const resp = await api.readWorkspaceFile(id, {
        path,
        offset: opts.offset ?? 1,
        limit: opts.limit ?? 2000,
      })
      if (sessionId.value !== id || selectedPath.value !== path) return
      fileContent.value = resp
    } catch (err) {
      if (sessionId.value !== id || selectedPath.value !== path) return
      if (err instanceof ApiError) fileError.value = err
      fileContent.value = null
    } finally {
      loadingFile.value = false
    }
  }

  async function loadMoreFile() {
    const cur = fileContent.value
    const path = selectedPath.value
    if (!cur || !path) return
    const id = sessionId.value
    if (!id) return
    const nextOffset = (cur.content.split('\n').length) + 1
    try {
      const resp = await api.readWorkspaceFile(id, {
        path,
        offset: nextOffset,
        limit: 2000,
      })
      if (sessionId.value !== id || selectedPath.value !== path) return
      fileContent.value = {
        ...resp,
        content: cur.content + (cur.content.endsWith('\n') ? '' : '\n') + resp.content,
      }
    } catch (err) {
      if (err instanceof ApiError) fileError.value = err
    }
  }

  function setSortMode(mode: SortMode) {
    sortMode.value = mode
  }

  function targetUploadDir(): string {
    const sel = selectedPath.value
    if (sel) {
      const entry = entries.value.get(sel)
      if (entry) {
        if (entry.type === 'directory') return sel
        const parent = parentOf(sel)
        return parent === '' ? '.' : parent
      }
    }
    return activeDir.value
  }

  async function createDirectory(
    name: string,
    opts: { parent?: string } = {},
  ): Promise<{ path: string; created: boolean }> {
    const id = sessionId.value
    if (!id) throw new Error('沒有作用中的 session')
    const trimmed = name.trim().replace(/^\/+|\/+$/g, '')
    if (!trimmed) throw new Error('資料夾名稱不能為空')

    const parent = opts.parent ?? targetUploadDir()
    const fullPath =
      parent === '.' || parent === '' ? trimmed : `${parent}/${trimmed}`

    const resp = await api.createWorkspaceDirectory(id, { path: fullPath })
    if (sessionId.value !== id) {
      return { path: resp.path, created: resp.created }
    }

    const parentKey = parent === '.' ? '' : parent
    if (parentKey === '' || expanded.value.has(parentKey)) {
      await refreshTree({ path: parent })
    }
    if (resp.created) notifyComposerOfMkdir(resp.path)
    return { path: resp.path, created: resp.created }
  }

  function basename(path: string): string {
    const i = path.lastIndexOf('/')
    return i < 0 ? path : path.slice(i + 1)
  }

  function isDescendantPath(parent: string, candidate: string): boolean {
    if (parent === '.' || parent === '') return candidate !== '.'
    return candidate === parent || candidate.startsWith(`${parent}/`)
  }

  function planMove(src: string, targetDir: string): string {
    const dir = targetDir === '' || targetDir === '.' ? '' : targetDir
    const name = basename(src)
    return dir === '' ? name : `${dir}/${name}`
  }

  async function moveEntry(
    src: string,
    dst: string,
    opts: { overwrite?: boolean } = {},
  ): Promise<void> {
    const id = sessionId.value
    if (!id) throw new Error('沒有作用中的 session')
    if (!src || src === '.') throw new Error('來源路徑不合法')
    if (!dst || dst === '.') throw new Error('目標路徑不合法')
    if (src === dst) return

    const srcEntry = entries.value.get(src)
    if (srcEntry?.type === 'directory' && isDescendantPath(src, dst)) {
      throw new Error('不能把資料夾搬到自己底下')
    }

    try {
      const resp = await api.moveWorkspaceEntry(id, {
        src,
        dst,
        overwrite: opts.overwrite ?? false,
      })
      if (sessionId.value !== id) return

      const srcParent = parentOf(src)
      const dstParent = parentOf(resp.dst)
      const dirsToRefresh = new Set<string>()
      if (srcParent === '' || expanded.value.has(srcParent)) {
        dirsToRefresh.add(srcParent)
      }
      if (dstParent === '' || expanded.value.has(dstParent)) {
        dirsToRefresh.add(dstParent)
      }
      await Promise.all(
        [...dirsToRefresh].map((d) =>
          refreshTree({ path: d === '' ? '.' : d }),
        ),
      )

      if (selectedPath.value === src) {
        await select(resp.dst)
      } else if (
        selectedPath.value &&
        selectedPath.value.startsWith(`${src}/`)
      ) {
        const rest = selectedPath.value.slice(src.length + 1)
        await select(`${resp.dst}/${rest}`)
      }

      if (expanded.value.has(src)) {
        const next = new Set(expanded.value)
        next.delete(src)
        if (resp.type === 'directory') next.add(resp.dst)
        expanded.value = next
      }

      notifyComposerOfMove(src, resp.dst)
    } catch (err) {
      if (
        err instanceof ApiError &&
        err.code === 'WORKSPACE_MOVE_DESTINATION_EXISTS'
      ) {
        pendingMoveConflict.value = { src, dst }
      }
      throw err
    }
  }

  function setDraggingPath(path: string | null) {
    draggingPath.value = path
  }

  function clearMoveConflict() {
    pendingMoveConflict.value = null
  }

  async function deleteFile(path: string): Promise<void> {
    const id = sessionId.value
    if (!id) throw new Error('沒有作用中的 session')
    if (!path || path === '.') throw new Error('路徑不合法')

    try {
      await api.deleteWorkspaceFile(id, { path })
      if (sessionId.value !== id) return

      const parent = parentOf(path)
      if (parent === '' || expanded.value.has(parent)) {
        await refreshTree({ path: parent === '' ? '.' : parent })
      }
      if (selectedPath.value === path) {
        await select(null)
      }
      toast.success('已刪除', { description: path })
      notifyComposerOfDelete(path)
    } catch (err) {
      toast.error('刪除失敗', { description: describeDeleteError(err) })
      throw err
    }
  }

  function enterEditMode() {
    const content = fileContent.value?.content ?? ''
    editContent.value = content
    editMode.value = true
  }

  function exitEditMode() {
    editMode.value = false
    editContent.value = ''
  }

  async function saveFile(): Promise<void> {
    const id = sessionId.value
    const path = selectedPath.value
    if (!id || !path || editSaving.value) return
    editSaving.value = true
    try {
      await api.saveWorkspaceFile(id, { path, content: editContent.value })
      if (sessionId.value !== id || selectedPath.value !== path) return
      // Reload file content and refresh tree entry for updated_at
      await loadFile(path)
      await refreshPaths([path])
      editMode.value = false
      editContent.value = ''
      toast.success('已儲存', { description: path })
      const bus = useComposerBus()
      bus.append(`（使用者編輯了檔案：「${path}」）`)
    } catch (err) {
      if (err instanceof ApiError) {
        toast.error('儲存失敗', { description: err.message })
      } else {
        toast.error('儲存失敗')
      }
      throw err
    } finally {
      editSaving.value = false
    }
  }

  async function createFile(
    name: string,
    opts: { parent?: string } = {},
  ): Promise<{ path: string; created: boolean }> {
    const id = sessionId.value
    if (!id) throw new Error('沒有作用中的 session')
    const trimmed = name.trim()
    if (!trimmed) throw new Error('檔案名稱不能為空')

    const parent = opts.parent ?? targetUploadDir()
    const fullPath =
      parent === '.' || parent === '' ? trimmed : `${parent}/${trimmed}`

    const resp = await api.createWorkspaceFile(id, { path: fullPath })
    if (sessionId.value !== id) return { path: resp.path, created: resp.created }

    const parentKey = parent === '.' ? '' : parent
    if (parentKey !== '') {
      expanded.value = new Set([...expanded.value, parentKey])
    }
    await refreshTree({ path: parent })
    await select(resp.path)
    if (resp.created) {
      const bus = useComposerBus()
      bus.append(`（使用者建立了檔案：「${resp.path}」）`)
    }
    return { path: resp.path, created: resp.created }
  }

  async function deleteDirectory(path: string): Promise<void> {
    const id = sessionId.value
    if (!id) throw new Error('沒有作用中的 session')
    if (!path || path === '.') throw new Error('路徑不合法')

    try {
      await api.deleteWorkspaceDirectory(id, { path, recursive: true })
      if (sessionId.value !== id) return

      const parent = parentOf(path)
      if (parent === '' || expanded.value.has(parent)) {
        await refreshTree({ path: parent === '' ? '.' : parent })
      }
      if (selectedPath.value === path || selectedPath.value?.startsWith(`${path}/`)) {
        await select(null)
      }
      if (expanded.value.has(path)) {
        const next = new Set(expanded.value)
        next.delete(path)
        expanded.value = next
      }
      toast.success('已刪除資料夾', { description: path })
      const bus = useComposerBus()
      bus.append(`（使用者刪除了資料夾：「${path}」）`)
    } catch (err) {
      if (err instanceof ApiError) {
        toast.error('刪除失敗', { description: err.message })
      } else {
        toast.error('刪除失敗')
      }
      throw err
    }
  }

  async function renameEntry(src: string, newName: string): Promise<void> {
    const trimmed = newName.trim()
    if (!trimmed) throw new Error('名稱不能為空')
    if (trimmed.includes('/'))
      throw new Error('名稱不能含 "/"，請改用拖拉移動')

    const parent = parentOf(src)
    const dst = parent === '' ? trimmed : `${parent}/${trimmed}`
    if (src === dst) return

    try {
      await moveEntry(src, dst)
      toast.success('已重新命名', { description: dst })
    } catch (err) {
      if (
        err instanceof ApiError &&
        err.code === 'WORKSPACE_MOVE_DESTINATION_EXISTS'
      ) {
        return
      }
      toast.error('重新命名失敗', { description: describeMoveError(err) })
      throw err
    }
  }

  function startRename(path: string) {
    const entry = entries.value.get(path)
    if (!entry) return
    pendingRename.value = {
      path,
      type: entry.type,
      name: entry.name,
    }
  }

  function clearRename() {
    pendingRename.value = null
  }

  function startDelete(path: string) {
    const entry = entries.value.get(path)
    if (!entry) return
    pendingDelete.value = { path, name: entry.name, type: entry.type }
  }

  function clearDelete() {
    pendingDelete.value = null
  }

  function notifyComposerOfUploads(paths: string[]) {
    if (paths.length === 0) return
    const list = paths.map((p) => `「${p}」`).join('、')
    const text =
      paths.length === 1
        ? `（使用者上傳了檔案：${list}）`
        : `（使用者上傳了 ${paths.length} 個檔案：${list}）`
    const bus = useComposerBus()
    bus.append(text)
  }

  function notifyComposerOfDelete(path: string) {
    if (!path) return
    const bus = useComposerBus()
    bus.append(`（使用者刪除了檔案：「${path}」）`)
  }

  function notifyComposerOfMove(src: string, dst: string) {
    const srcParent = parentOf(src)
    const dstParent = parentOf(dst)
    const isRename = srcParent === dstParent
    const text = isRename
      ? `（使用者把「${src}」重新命名為「${dst}」）`
      : `（使用者把「${src}」移動到「${dst}」）`
    const bus = useComposerBus()
    bus.append(text)
  }

  function notifyComposerOfMkdir(path: string) {
    if (!path) return
    const bus = useComposerBus()
    bus.append(`（使用者建立了資料夾：「${path}」）`)
  }

  async function uploadFiles(
    files: File[],
    opts: { path?: string; overwrite?: boolean } = {},
  ): Promise<WorkspaceUploadResponse> {
    const id = sessionId.value
    if (!id) throw new Error('沒有作用中的 session')
    if (files.length === 0) throw new Error('沒有檔案可上傳')

    const target = opts.path ?? targetUploadDir()
    const resp = await api.uploadWorkspaceFiles(
      id,
      { path: target, overwrite: opts.overwrite ?? false },
      files,
    )
    if (sessionId.value !== id) return resp

    const dirKey = target === '.' ? '' : target
    if (dirKey === '' || expanded.value.has(dirKey)) {
      await refreshTree({ path: target })
    }
    return resp
  }

  function validateUploadCandidates(files: File[]): File[] | null {
    if (files.length === 0) return null
    if (files.length > MAX_UPLOAD_FILES_PER_REQUEST) {
      toast.error('檔案數量超過上限', {
        description: `單次最多上傳 ${MAX_UPLOAD_FILES_PER_REQUEST} 個檔案`,
      })
      return null
    }
    const tooBig = files.filter((f) => f.size > MAX_UPLOAD_FILE_BYTES)
    if (tooBig.length > 0) {
      toast.error('檔案大小超過上限', {
        description: `單檔上限 ${formatBytes(
          MAX_UPLOAD_FILE_BYTES,
        )}，超過的檔案：${tooBig.map((f) => f.name).join('、')}`,
      })
      return null
    }
    return files
  }

  async function triggerUpload(
    files: File[],
    target: string,
    opts: { overwrite?: boolean } = {},
  ): Promise<void> {
    const ok = opts.overwrite ? files : validateUploadCandidates(files)
    if (!ok) return
    uploading.value = true
    try {
      const resp = await uploadFiles(ok, {
        path: target,
        overwrite: opts.overwrite ?? false,
      })
      if (resp.uploaded.length > 0) {
        const action = opts.overwrite ? '覆寫' : '上傳'
        const desc = target === '.' ? 'workspace 根目錄' : target
        toast.success(`${action}成功`, {
          description: `${resp.uploaded.length} 個檔案 → ${desc}`,
        })
        notifyComposerOfUploads(resp.uploaded.map((u) => u.path))
      }
      if (resp.skipped.length > 0) {
        uploadConflict.value = {
          files: ok.filter((f) =>
            resp.skipped.some((s) => s.name === f.name),
          ),
          names: resp.skipped.map((s) => s.name),
          target,
        }
      } else {
        uploadConflict.value = null
      }
    } catch (err) {
      toast.error('上傳失敗', { description: describeUploadError(err) })
    } finally {
      uploading.value = false
    }
  }

  async function confirmUploadOverwrite(): Promise<void> {
    const conflict = uploadConflict.value
    if (!conflict) return
    const { files, target } = conflict
    uploadConflict.value = null
    await triggerUpload(files, target, { overwrite: true })
  }

  function dismissUploadConflict() {
    uploadConflict.value = null
  }

  function childrenOf(dir: string): WorkspaceEntryDTO[] {
    const out: WorkspaceEntryDTO[] = []
    for (const e of entries.value.values()) {
      if (parentOf(e.path) === dir) out.push(e)
    }
    return sortEntries(out)
  }

  function sortEntries(list: WorkspaceEntryDTO[]): WorkspaceEntryDTO[] {
    const dirs = list.filter((e) => e.type === 'directory')
    const files = list.filter((e) => e.type === 'file')
    const cmp =
      sortMode.value === 'updated'
        ? (a: WorkspaceEntryDTO, b: WorkspaceEntryDTO) =>
            b.updated_at.localeCompare(a.updated_at)
        : (a: WorkspaceEntryDTO, b: WorkspaceEntryDTO) =>
            a.name.localeCompare(b.name)
    dirs.sort(cmp)
    files.sort(cmp)
    return [...dirs, ...files]
  }

  const rootChildren = computed(() => childrenOf(''))
  const hasContent = computed(() => entries.value.size > 0)

  return {
    sessionId,
    entries,
    expanded,
    selectedPath,
    fileContent,
    fileError,
    loadingFile,
    loadState,
    lastSyncedAt,
    sortMode,
    visible,
    activeTab,
    draggingPath,
    pendingMoveConflict,
    uploading,
    uploadConflict,
    pendingRename,
    pendingDelete,
    mkdirRequest,
    pendingNewFile,
    openMkdir,
    closeMkdir,
    openNewFile,
    closeNewFile,
    rootChildren,
    hasContent,
    bind,
    refreshTree,
    refreshExpanded,
    refreshPaths,
    expand,
    collapse,
    toggleExpand,
    select,
    loadFile,
    loadMoreFile,
    setSortMode,
    setVisible,
    toggleVisible,
    setActiveTab,
    focusBrowser,
    focusAgents,
    childrenOf,
    getDir,
    uploadFiles,
    triggerUpload,
    confirmUploadOverwrite,
    dismissUploadConflict,
    createDirectory,
    targetUploadDir,
    moveEntry,
    planMove,
    isDescendantPath,
    setDraggingPath,
    clearMoveConflict,
    editMode,
    editContent,
    editSaving,
    enterEditMode,
    exitEditMode,
    saveFile,
    deleteFile,
    deleteDirectory,
    createFile,
    renameEntry,
    startRename,
    clearRename,
    startDelete,
    clearDelete,
  }
})

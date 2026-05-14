import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/lib/api'
import { ApiError } from '@/lib/errors'
import type { WorkspaceEntryDTO, WorkspaceFileResponse } from '@/lib/types'

const VISIBLE_STORAGE_KEY = 'picobot:workspace:visible'

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
    else await expand(path)
  }

  async function select(path: string | null) {
    selectedPath.value = path
    if (!path) {
      fileContent.value = null
      fileError.value = null
      return
    }
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
    childrenOf,
    getDir,
  }
})

<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  ChevronRight,
  File,
  Folder,
  FolderOpen,
  Loader2,
  Pencil,
  Trash2,
  Download,
  FilePlus,
} from 'lucide-vue-next'
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from '@/components/ui/context-menu'
import { toast } from 'vue-sonner'
import { useWorkspaceStore } from '@/stores/workspace'
import { useCapabilitiesStore } from '@/stores/capabilities'
import { useRelativeTime } from '@/composables/useRelativeTime'
import { ApiError } from '@/lib/errors'
import { api } from '@/lib/api'
import type { WorkspaceEntryDTO } from '@/lib/types'

const INTERNAL_DRAG_TYPE = 'application/x-picobot-path'

const props = defineProps<{
  entry: WorkspaceEntryDTO
  depth: number
}>()

const ws = useWorkspaceStore()
const caps = useCapabilitiesStore()

const isDir = computed(() => props.entry.type === 'directory')
const isExpanded = computed(() => ws.expanded.has(props.entry.path))
const isSelected = computed(() => ws.selectedPath === props.entry.path)
const dirState = computed(() => ws.getDir(props.entry.path))
const children = computed(() =>
  isDir.value && isExpanded.value ? ws.childrenOf(props.entry.path) : [],
)

const { text: relative } = useRelativeTime(() => props.entry.updated_at)

const dragOverDepth = ref(0)
const dragKind = ref<'internal' | 'external' | null>(null)
const isDragSelf = computed(() => ws.draggingPath === props.entry.path)
const isDropTarget = computed(() => {
  if (!isDir.value) return false
  if (dragOverDepth.value === 0) return false
  if (dragKind.value === 'internal') {
    const src = ws.draggingPath
    if (!src) return false
    if (ws.isDescendantPath(src, props.entry.path)) return false
    return true
  }
  return dragKind.value === 'external'
})

function onClick() {
  if (isDir.value) {
    void ws.toggleExpand(props.entry.path)
  } else {
    void ws.select(props.entry.path)
  }
}

function onDragStart(e: DragEvent) {
  if (!e.dataTransfer) return
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData(INTERNAL_DRAG_TYPE, props.entry.path)
  e.dataTransfer.setData('text/plain', props.entry.path)
  ws.setDraggingPath(props.entry.path)
}

function onDragEnd() {
  ws.setDraggingPath(null)
  dragOverDepth.value = 0
}

function detectDragKind(e: DragEvent): 'internal' | 'external' | null {
  const types = e.dataTransfer?.types as unknown as Iterable<string> | undefined
  if (!types) return null
  for (const t of types) {
    if (t === INTERNAL_DRAG_TYPE) return 'internal'
  }
  for (const t of types) {
    if (t === 'Files') return 'external'
  }
  return null
}

function isExternalUploadAvailable(): boolean {
  return caps.data.features.file_upload
}

function onDragEnter(e: DragEvent) {
  if (!isDir.value) return
  const kind = detectDragKind(e)
  if (!kind) return
  if (kind === 'internal') {
    if (isDragSelf.value) return
    const src = ws.draggingPath
    if (src && ws.isDescendantPath(src, props.entry.path)) return
  } else if (kind === 'external') {
    if (!isExternalUploadAvailable()) return
  }
  e.preventDefault()
  e.stopPropagation()
  dragKind.value = kind
  dragOverDepth.value += 1
}

function onDragOver(e: DragEvent) {
  if (!isDir.value) return
  const kind = detectDragKind(e)
  if (!kind) return
  if (kind === 'internal') {
    if (isDragSelf.value) return
    const src = ws.draggingPath
    if (src && ws.isDescendantPath(src, props.entry.path)) return
    e.preventDefault()
    e.stopPropagation()
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
  } else {
    if (!isExternalUploadAvailable()) return
    e.preventDefault()
    e.stopPropagation()
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
  }
}

function onDragLeave(e: DragEvent) {
  if (!isDir.value) return
  const kind = detectDragKind(e)
  if (!kind) return
  dragOverDepth.value = Math.max(0, dragOverDepth.value - 1)
  if (dragOverDepth.value === 0) dragKind.value = null
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case 'WORKSPACE_MOVE_INTO_SELF':
        return '不能搬到自己底下'
      case 'WORKSPACE_MOVE_SAME_PATH':
        return '來源和目標相同'
      case 'WORKSPACE_MOVE_ROOT_FORBIDDEN':
        return '不能搬動 workspace 根目錄'
      case 'WORKSPACE_MOVE_DESTINATION_IS_DIRECTORY':
        return '目標位置已是資料夾，無法合併'
      case 'WORKSPACE_DIRECTORY_NOT_FOUND':
        return '目標的父目錄不存在'
      case 'WORKSPACE_FILE_NOT_FOUND':
        return '來源已不存在'
      case 'WORKSPACE_PATH_INVALID':
        return '路徑不合法'
      case 'WORKSPACE_MOVE_DESTINATION_EXISTS':
        return ''
      default:
        return err.message
    }
  }
  return err instanceof Error ? err.message : '移動失敗'
}

async function onDrop(e: DragEvent) {
  if (!isDir.value) return
  const kind = detectDragKind(e)
  if (!kind) return
  e.preventDefault()
  e.stopPropagation()
  dragOverDepth.value = 0
  dragKind.value = null

  if (kind === 'external') {
    const files = Array.from(e.dataTransfer?.files ?? [])
    if (files.length === 0) return
    if (!isExpanded.value) await ws.expand(props.entry.path)
    await ws.triggerUpload(files, props.entry.path)
    return
  }

  const src = e.dataTransfer?.getData(INTERNAL_DRAG_TYPE) || ws.draggingPath
  ws.setDraggingPath(null)
  if (!src || src === props.entry.path) return
  if (ws.isDescendantPath(src, props.entry.path)) return

  const dst = ws.planMove(src, props.entry.path)
  if (!isExpanded.value) await ws.expand(props.entry.path)
  try {
    await ws.moveEntry(src, dst)
  } catch (err) {
    if (
      err instanceof ApiError &&
      err.code === 'WORKSPACE_MOVE_DESTINATION_EXISTS'
    ) {
      return
    }
    toast.error('移動失敗', { description: describeError(err) })
  }
}

const indentStyle = computed(() => ({
  paddingLeft: `${props.depth * 12 + 6}px`,
}))

function downloadEntry() {
  const id = ws.sessionId
  if (!id || isDir.value) return
  const base = api.workspaceFileRawUrl(id, props.entry.path)
  const url = `${base}&download=true`
  const a = document.createElement('a')
  a.href = url
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}
</script>

<template>
  <div>
    <ContextMenu>
      <ContextMenuTrigger as-child>
        <button
          type="button"
          :draggable="true"
          class="group flex w-full items-center gap-1 rounded px-1.5 py-1 text-left text-xs transition-colors"
          :class="[
            isSelected
              ? 'bg-accent text-accent-foreground'
              : 'hover:bg-accent/60',
            isDropTarget ? 'outline outline-2 outline-brand/60 bg-brand/10' : '',
            isDragSelf ? 'opacity-40' : '',
          ]"
          :style="indentStyle"
          @click="onClick"
          @dragstart="onDragStart"
          @dragend="onDragEnd"
          @dragenter="onDragEnter"
          @dragover="onDragOver"
          @dragleave="onDragLeave"
          @drop="onDrop"
        >
          <ChevronRight
            v-if="isDir"
            class="size-3 shrink-0 transition-transform"
            :class="isExpanded ? 'rotate-90' : ''"
          />
          <span v-else class="size-3 shrink-0" />

          <Loader2
            v-if="isDir && dirState.loading"
            class="size-3.5 shrink-0 animate-spin text-muted-foreground"
          />
          <FolderOpen
            v-else-if="isDir && isExpanded"
            class="size-3.5 shrink-0 text-amber-500"
          />
          <Folder
            v-else-if="isDir"
            class="size-3.5 shrink-0 text-amber-500"
          />
          <File v-else class="size-3.5 shrink-0 text-muted-foreground" />

          <span class="flex-1 truncate font-mono">{{ entry.name }}</span>
          <span
            class="hidden shrink-0 text-[10px] text-muted-foreground group-hover:inline"
            :title="entry.updated_at"
          >
            {{ relative }}
          </span>
        </button>
      </ContextMenuTrigger>
      <ContextMenuContent class="w-48">
        <ContextMenuItem
          v-if="isDir"
          @select="ws.openNewFile(entry.path)"
        >
          <FilePlus class="size-3.5" />
          新增檔案
        </ContextMenuItem>
        <ContextMenuItem @select="ws.startRename(entry.path)">
          <Pencil class="size-3.5" />
          重新命名
        </ContextMenuItem>
        <ContextMenuItem
          v-if="!isDir"
          @select="downloadEntry"
        >
          <Download class="size-3.5" />
          下載
        </ContextMenuItem>
        <ContextMenuItem
          class="text-destructive focus:text-destructive"
          @select="ws.startDelete(entry.path)"
        >
          <Trash2 class="size-3.5" />
          刪除
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>

    <template v-if="isDir && isExpanded">
      <WorkspaceTreeNode
        v-for="child in children"
        :key="child.path"
        :entry="child"
        :depth="depth + 1"
      />
      <p
        v-if="dirState.truncated"
        class="ml-6 text-[10px] italic text-muted-foreground"
      >
        … 已截斷，可能還有檔案
      </p>
    </template>
  </div>
</template>

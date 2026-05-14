<script setup lang="ts">
import { computed, ref } from 'vue'
import { toast } from 'vue-sonner'
import { useWorkspaceStore } from '@/stores/workspace'
import { useCapabilitiesStore } from '@/stores/capabilities'
import WorkspaceTreeNode from './WorkspaceTreeNode.vue'
import WorkspaceEmpty from './WorkspaceEmpty.vue'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/errors'

const INTERNAL_DRAG_TYPE = 'application/x-picobot-path'

const ws = useWorkspaceStore()
const caps = useCapabilitiesStore()
const rootDragDepth = ref(0)
const rootDragKind = ref<'internal' | 'external' | null>(null)

const isRootDropTarget = computed(() => {
  if (rootDragDepth.value === 0) return false
  if (rootDragKind.value === 'external') return true
  const src = ws.draggingPath
  if (!src) return false
  if (srcIsRootChild(src)) return false
  return true
})

function detectDragKind(e: DragEvent): 'internal' | 'external' | null {
  const types = e.dataTransfer?.types as unknown as Iterable<string> | undefined
  if (!types) return null
  for (const t of types) if (t === INTERNAL_DRAG_TYPE) return 'internal'
  for (const t of types) if (t === 'Files') return 'external'
  return null
}

function srcIsRootChild(src: string): boolean {
  return !src.includes('/')
}

function shouldAccept(kind: 'internal' | 'external'): boolean {
  if (kind === 'external') return caps.data.features.file_upload
  const src = ws.draggingPath
  return !!src && !srcIsRootChild(src)
}

function onDragEnter(e: DragEvent) {
  const kind = detectDragKind(e)
  if (!kind || !shouldAccept(kind)) return
  e.preventDefault()
  rootDragKind.value = kind
  rootDragDepth.value += 1
}

function onDragOver(e: DragEvent) {
  const kind = detectDragKind(e)
  if (!kind || !shouldAccept(kind)) return
  e.preventDefault()
  if (e.dataTransfer) {
    e.dataTransfer.dropEffect = kind === 'external' ? 'copy' : 'move'
  }
}

function onDragLeave(e: DragEvent) {
  const kind = detectDragKind(e)
  if (!kind) return
  rootDragDepth.value = Math.max(0, rootDragDepth.value - 1)
  if (rootDragDepth.value === 0) rootDragKind.value = null
}

function describeError(err: unknown): string {
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
  return err instanceof Error ? err.message : '移動失敗'
}

async function onDrop(e: DragEvent) {
  const kind = detectDragKind(e)
  if (!kind || !shouldAccept(kind)) return
  e.preventDefault()
  rootDragDepth.value = 0
  rootDragKind.value = null

  if (kind === 'external') {
    const files = Array.from(e.dataTransfer?.files ?? [])
    if (files.length === 0) return
    await ws.triggerUpload(files, '.')
    return
  }

  const src = e.dataTransfer?.getData(INTERNAL_DRAG_TYPE) || ws.draggingPath
  ws.setDraggingPath(null)
  if (!src || srcIsRootChild(src)) return

  const dst = ws.planMove(src, '.')
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
</script>

<template>
  <div class="flex h-full flex-col overflow-hidden">
    <template v-if="ws.loadState === 'loading' && !ws.hasContent">
      <div class="space-y-2 p-3">
        <Skeleton v-for="i in 4" :key="i" class="h-5 w-full" />
      </div>
    </template>
    <template v-else-if="ws.loadState === 'unavailable'">
      <WorkspaceEmpty variant="unavailable" />
    </template>
    <template v-else-if="ws.loadState === 'error'">
      <WorkspaceEmpty variant="error" />
    </template>
    <template v-else>
      <div
        class="flex-1 overflow-y-auto px-1 py-2 transition-colors"
        :class="
          isRootDropTarget
            ? 'outline-dashed outline-2 outline-brand/50 -outline-offset-4'
            : ''
        "
        @dragenter="onDragEnter"
        @dragover="onDragOver"
        @dragleave="onDragLeave"
        @drop="onDrop"
      >
        <WorkspaceEmpty v-if="ws.loadState === 'empty'" variant="empty" />
        <WorkspaceTreeNode
          v-for="entry in ws.rootChildren"
          :key="entry.path"
          :entry="entry"
          :depth="0"
        />
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import WorkspaceHeader from './WorkspaceHeader.vue'
import WorkspaceTree from './WorkspaceTree.vue'
import WorkspaceFilePreview from './WorkspaceFilePreview.vue'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useVerticalSplit } from '@/composables/useVerticalSplit'
import { useHorizontalResize } from '@/composables/useHorizontalResize'
import { useWorkspaceStore } from '@/stores/workspace'
import { ApiError } from '@/lib/errors'

const ws = useWorkspaceStore()

const { containerRef, ratio, onPointerDown: onSplitPointerDown } =
  useVerticalSplit({
    storageKey: 'picobot:workspace:split',
    initial: 0.45,
    min: 0.15,
    max: 0.85,
  })

const { targetRef, width, onPointerDown: onWidthPointerDown } =
  useHorizontalResize({
    storageKey: 'picobot:workspace:width',
    initial: 320,
    min: 240,
    max: 720,
    edge: 'left',
  })

const treeStyle = computed(() => ({ flex: `${ratio.value} 1 0` }))
const previewStyle = computed(() => ({ flex: `${1 - ratio.value} 1 0` }))
const panelStyle = computed(() => ({ width: `${width.value}px` }))

const uploadConflict = computed(() => ws.uploadConflict)
const showUploadConflict = computed(() => uploadConflict.value !== null)
const moveConflict = computed(() => ws.pendingMoveConflict)
const showMoveConflict = computed(() => moveConflict.value !== null)
const movingOverwrite = ref(false)

const renameTarget = computed(() => ws.pendingRename)
const showRename = computed(() => renameTarget.value !== null)
const renameInput = ref('')
const renaming = ref(false)
const renameInputRef = ref<HTMLInputElement | null>(null)

const deleteTarget = computed(() => ws.pendingDelete)
const showDelete = computed(() => deleteTarget.value !== null)
const deleting = ref(false)

watch(renameTarget, async (target) => {
  if (target) {
    renameInput.value = target.name
    await nextTick()
    renameInputRef.value?.focus()
    renameInputRef.value?.select()
  }
})

async function submitRename() {
  const target = renameTarget.value
  if (!target || renaming.value) return
  const next = renameInput.value.trim()
  if (!next || next === target.name) {
    ws.clearRename()
    return
  }
  renaming.value = true
  try {
    await ws.renameEntry(target.path, next)
    ws.clearRename()
  } catch {
    // toast already handled in store
  } finally {
    renaming.value = false
  }
}

async function confirmDelete() {
  const target = deleteTarget.value
  if (!target || deleting.value) return
  deleting.value = true
  try {
    await ws.deleteFile(target.path)
    ws.clearDelete()
  } catch {
    // toast already handled in store
  } finally {
    deleting.value = false
  }
}

async function onHeaderUpload(files: File[]) {
  await ws.triggerUpload(files, ws.targetUploadDir())
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
  return err instanceof Error ? err.message : '移動失敗'
}

async function confirmMoveOverwrite() {
  const conflict = moveConflict.value
  if (!conflict || movingOverwrite.value) return
  movingOverwrite.value = true
  try {
    ws.clearMoveConflict()
    await ws.moveEntry(conflict.src, conflict.dst, { overwrite: true })
    toast.success('已覆寫', { description: conflict.dst })
  } catch (err) {
    toast.error('移動失敗', { description: describeMoveError(err) })
  } finally {
    movingOverwrite.value = false
  }
}

function dismissMoveConflict() {
  ws.clearMoveConflict()
}
</script>

<template>
  <aside
    ref="targetRef"
    class="relative flex h-full shrink-0 flex-col border-l bg-background"
    :style="panelStyle"
  >
    <div
      class="group absolute inset-y-0 -left-1 z-10 w-2 cursor-col-resize"
      role="separator"
      aria-orientation="vertical"
      aria-label="拖曳調整 workspace 寬度"
      @pointerdown="onWidthPointerDown"
    >
      <span
        class="pointer-events-none absolute inset-y-0 left-1/2 -translate-x-1/2 w-px bg-transparent transition-colors group-hover:bg-primary/40"
      />
    </div>

    <WorkspaceHeader @upload="onHeaderUpload" />
    <div ref="containerRef" class="flex min-h-0 flex-1 flex-col">
      <WorkspaceTree
        class="min-h-0 overflow-hidden"
        :style="treeStyle"
      />
      <div
        class="group relative h-1.5 shrink-0 cursor-row-resize bg-border transition-colors hover:bg-primary/40"
        role="separator"
        aria-orientation="horizontal"
        aria-label="拖曳調整上下比例"
        @pointerdown="onSplitPointerDown"
      >
        <span
          class="pointer-events-none absolute inset-x-0 top-1/2 -translate-y-1/2 mx-auto block h-0.5 w-8 rounded-full bg-foreground/20 transition-colors group-hover:bg-foreground/50"
        />
      </div>
      <WorkspaceFilePreview
        class="min-h-0 overflow-hidden"
        :style="previewStyle"
      />
    </div>

    <Dialog
      :open="showRename"
      @update:open="(v) => !v && ws.clearRename()"
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>重新命名</DialogTitle>
          <DialogDescription>
            原名稱：
            <span class="font-mono text-foreground">{{ renameTarget?.name }}</span>
          </DialogDescription>
        </DialogHeader>
        <input
          ref="renameInputRef"
          v-model="renameInput"
          class="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          placeholder="新名稱"
          @keydown.enter.prevent="submitRename"
          @keydown.esc.prevent="ws.clearRename()"
        />
        <DialogFooter>
          <Button variant="outline" @click="ws.clearRename()">取消</Button>
          <Button
            :disabled="
              !renameInput.trim() ||
              renaming ||
              renameInput.trim() === renameTarget?.name
            "
            @click="submitRename"
          >
            確定
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog
      :open="showDelete"
      @update:open="(v) => !v && ws.clearDelete()"
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>確定刪除？</DialogTitle>
          <DialogDescription>
            <span class="font-mono">{{ deleteTarget?.path }}</span>
            將被永久刪除，此操作無法復原。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" @click="ws.clearDelete()">取消</Button>
          <Button
            variant="destructive"
            :disabled="deleting"
            @click="confirmDelete"
          >
            刪除
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog
      :open="showMoveConflict"
      @update:open="(v) => !v && dismissMoveConflict()"
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>目標已存在</DialogTitle>
          <DialogDescription>
            <span class="font-mono">{{ moveConflict?.dst }}</span>
            已存在，要覆寫嗎？此操作不可復原。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" @click="dismissMoveConflict">取消</Button>
          <Button
            variant="destructive"
            :disabled="movingOverwrite"
            @click="confirmMoveOverwrite"
          >
            覆寫
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog
      :open="showUploadConflict"
      @update:open="(v) => !v && ws.dismissUploadConflict()"
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>檔案已存在</DialogTitle>
          <DialogDescription>
            下列 {{ uploadConflict?.names.length }} 個檔案在
            「{{
              uploadConflict?.target === '.'
                ? '根目錄'
                : uploadConflict?.target
            }}」已存在，要覆寫嗎？
          </DialogDescription>
        </DialogHeader>
        <ul
          class="max-h-48 overflow-y-auto rounded-md border bg-muted/30 p-2 text-xs font-mono"
        >
          <li
            v-for="n in uploadConflict?.names ?? []"
            :key="n"
            class="truncate py-0.5"
          >
            {{ n }}
          </li>
        </ul>
        <DialogFooter>
          <Button variant="outline" @click="ws.dismissUploadConflict()">
            取消
          </Button>
          <Button :disabled="ws.uploading" @click="ws.confirmUploadOverwrite()">
            覆寫
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </aside>
</template>

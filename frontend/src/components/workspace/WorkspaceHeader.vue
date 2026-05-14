<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import {
  RefreshCw,
  X,
  ArrowDownAZ,
  Clock,
  Upload,
  FolderPlus,
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useWorkspaceStore } from '@/stores/workspace'
import { useCapabilitiesStore } from '@/stores/capabilities'
import { ApiError } from '@/lib/errors'

const emit = defineEmits<{ (e: 'upload', files: File[]): void }>()

const ws = useWorkspaceStore()
const caps = useCapabilitiesStore()
const fileInputRef = ref<HTMLInputElement | null>(null)

const showMkdir = ref(false)
const folderName = ref('')
const mkdirInputRef = ref<HTMLInputElement | null>(null)
const creating = ref(false)

const mkdirTarget = computed(() => {
  const t = ws.targetUploadDir()
  return t === '.' ? '/ (根目錄)' : t
})

function openPicker() {
  fileInputRef.value?.click()
}

function onFilesChosen(e: Event) {
  const input = e.target as HTMLInputElement
  const list = input.files ? Array.from(input.files) : []
  if (list.length > 0) emit('upload', list)
  input.value = ''
}

function openMkdir() {
  folderName.value = ''
  showMkdir.value = true
}

watch(showMkdir, async (open) => {
  if (open) {
    await nextTick()
    mkdirInputRef.value?.focus()
  }
})

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case 'WORKSPACE_NOT_AVAILABLE':
        return '此 session 沒有啟用 workspace'
      case 'WORKSPACE_PATH_INVALID':
        return '路徑不合法'
      case 'WORKSPACE_NOT_A_DIRECTORY':
        return '同名項目已存在但不是資料夾'
      default:
        return err.message
    }
  }
  return err instanceof Error ? err.message : '建立失敗'
}

async function submitMkdir() {
  const name = folderName.value.trim()
  if (!name || creating.value) return
  creating.value = true
  try {
    const result = await ws.createDirectory(name)
    showMkdir.value = false
    if (result.created) {
      toast.success('資料夾已建立', { description: result.path })
    } else {
      toast.info('資料夾已存在', { description: result.path })
    }
  } catch (err) {
    toast.error('建立資料夾失敗', { description: describeError(err) })
  } finally {
    creating.value = false
  }
}
</script>

<template>
  <header
    class="flex h-12 shrink-0 items-center gap-2 border-b bg-background px-3"
  >
    <span class="text-sm font-medium">Workspace</span>
    <div class="ml-auto flex items-center gap-1">
      <Button
        v-if="caps.data.features.file_upload"
        variant="ghost"
        size="icon"
        class="size-7"
        aria-label="上傳檔案"
        title="上傳檔案"
        @click="openPicker"
      >
        <Upload class="size-4" />
      </Button>
      <Button
        v-if="caps.data.features.session_workspace"
        variant="ghost"
        size="icon"
        class="size-7"
        aria-label="新增資料夾"
        title="新增資料夾"
        @click="openMkdir"
      >
        <FolderPlus class="size-4" />
      </Button>
      <input
        ref="fileInputRef"
        type="file"
        multiple
        class="hidden"
        @change="onFilesChosen"
      />
      <Button
        v-if="ws.sortMode === 'updated'"
        variant="ghost"
        size="icon"
        class="size-7"
        aria-label="改用名稱排序"
        title="目前：依修改時間"
        @click="ws.setSortMode('name')"
      >
        <Clock class="size-4" />
      </Button>
      <Button
        v-else
        variant="ghost"
        size="icon"
        class="size-7"
        aria-label="改用修改時間排序"
        title="目前：依名稱"
        @click="ws.setSortMode('updated')"
      >
        <ArrowDownAZ class="size-4" />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        class="size-7"
        aria-label="重新整理"
        title="重新整理"
        @click="ws.refreshExpanded()"
      >
        <RefreshCw class="size-4" />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        class="size-7"
        aria-label="關閉 workspace"
        title="關閉"
        @click="ws.setVisible(false)"
      >
        <X class="size-4" />
      </Button>
    </div>

    <Dialog v-model:open="showMkdir">
      <DialogContent>
        <DialogHeader>
          <DialogTitle>新增資料夾</DialogTitle>
          <DialogDescription>
            將建立在
            <span class="font-mono text-foreground">{{ mkdirTarget }}</span>
            底下。可用 <code>a/b/c</code> 一次建立巢狀資料夾。
          </DialogDescription>
        </DialogHeader>
        <input
          ref="mkdirInputRef"
          v-model="folderName"
          class="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          placeholder="資料夾名稱"
          @keydown.enter.prevent="submitMkdir"
          @keydown.esc.prevent="showMkdir = false"
        />
        <DialogFooter>
          <Button variant="outline" @click="showMkdir = false">取消</Button>
          <Button
            :disabled="!folderName.trim() || creating"
            @click="submitMkdir"
          >
            建立
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </header>
</template>

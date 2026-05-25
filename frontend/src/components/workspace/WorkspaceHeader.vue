<script setup lang="ts">
import { ref } from 'vue'
import type { WorkspaceTab } from '@/stores/workspace'
import {
  RefreshCw,
  X,
  ArrowDownAZ,
  Clock,
  Upload,
  FolderUp,
  FolderPlus,
  FilePlus,
  ArchiveIcon,
  Folder,
  Globe,
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useWorkspaceStore } from '@/stores/workspace'
import { useCapabilitiesStore } from '@/stores/capabilities'
import { api } from '@/lib/api'

const props = defineProps<{ tab: WorkspaceTab }>()
const emit = defineEmits<{
  (e: 'upload', files: File[]): void
  (e: 'update:tab', value: WorkspaceTab): void
}>()

const ws = useWorkspaceStore()
const caps = useCapabilitiesStore()
const fileInputRef = ref<HTMLInputElement | null>(null)
const folderInputRef = ref<HTMLInputElement | null>(null)

function downloadZip() {
  const id = ws.sessionId
  if (!id) return
  const url = api.workspaceDownloadUrl(id)
  const a = document.createElement('a')
  a.href = url
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

function openPicker() {
  fileInputRef.value?.click()
}

function openFolderPicker() {
  folderInputRef.value?.click()
}

function onFilesChosen(e: Event) {
  const input = e.target as HTMLInputElement
  const list = input.files ? Array.from(input.files) : []
  if (list.length > 0) emit('upload', list)
  input.value = ''
}

function tabBtnClass(t: WorkspaceTab): string {
  const base =
    'inline-flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors'
  return props.tab === t
    ? `${base} bg-background text-foreground shadow-sm`
    : `${base} text-muted-foreground hover:text-foreground`
}
</script>

<template>
  <header
    class="flex h-12 shrink-0 items-center gap-2 border-b bg-background px-3"
  >
    <div
      class="flex items-center gap-0.5 rounded-md border bg-muted/40 p-0.5"
      role="tablist"
    >
      <button
        type="button"
        role="tab"
        :aria-selected="tab === 'files'"
        :class="tabBtnClass('files')"
        @click="emit('update:tab', 'files')"
      >
        <Folder class="size-3.5" />
        檔案
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="tab === 'browser'"
        :class="tabBtnClass('browser')"
        @click="emit('update:tab', 'browser')"
      >
        <Globe class="size-3.5" />
        瀏覽器
      </button>
    </div>
    <TooltipProvider :delay-duration="200">
      <div class="ml-auto flex items-center gap-1">
        <template v-if="tab === 'files'">
          <Tooltip v-if="caps.data.features.file_upload">
            <TooltipTrigger as-child>
              <Button
                variant="ghost"
                size="icon"
                class="size-7"
                aria-label="上傳檔案"
                @click="openPicker"
              >
                <Upload class="size-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>上傳檔案</TooltipContent>
          </Tooltip>
          <Tooltip v-if="caps.data.features.file_upload">
            <TooltipTrigger as-child>
              <Button
                variant="ghost"
                size="icon"
                class="size-7"
                aria-label="上傳資料夾"
                @click="openFolderPicker"
              >
                <FolderUp class="size-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>上傳資料夾</TooltipContent>
          </Tooltip>
          <Tooltip v-if="caps.data.features.session_workspace">
            <TooltipTrigger as-child>
              <Button
                variant="ghost"
                size="icon"
                class="size-7"
                aria-label="新增檔案"
                @click="ws.openNewFile()"
              >
                <FilePlus class="size-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>新增檔案</TooltipContent>
          </Tooltip>
          <Tooltip v-if="caps.data.features.session_workspace">
            <TooltipTrigger as-child>
              <Button
                variant="ghost"
                size="icon"
                class="size-7"
                aria-label="新增資料夾"
                @click="ws.openMkdir()"
              >
                <FolderPlus class="size-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>新增資料夾</TooltipContent>
          </Tooltip>
          <input
            ref="fileInputRef"
            type="file"
            multiple
            class="hidden"
            @change="onFilesChosen"
          />
          <input
            ref="folderInputRef"
            type="file"
            webkitdirectory
            multiple
            class="hidden"
            @change="onFilesChosen"
          />
          <Tooltip>
            <TooltipTrigger as-child>
              <Button
                v-if="ws.sortMode === 'updated'"
                variant="ghost"
                size="icon"
                class="size-7"
                aria-label="改用名稱排序"
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
                @click="ws.setSortMode('updated')"
              >
                <ArrowDownAZ class="size-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              {{ ws.sortMode === 'updated' ? '目前：依修改時間' : '目前：依名稱' }}
            </TooltipContent>
          </Tooltip>
          <Tooltip v-if="caps.data.features.session_workspace">
            <TooltipTrigger as-child>
              <Button
                variant="ghost"
                size="icon"
                class="size-7"
                aria-label="下載 ZIP"
                @click="downloadZip"
              >
                <ArchiveIcon class="size-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>下載整個 Workspace</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger as-child>
              <Button
                variant="ghost"
                size="icon"
                class="size-7"
                aria-label="重新整理"
                @click="ws.refreshExpanded()"
              >
                <RefreshCw class="size-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>重新整理</TooltipContent>
          </Tooltip>
          <span class="mx-1 h-5 w-px bg-border" aria-hidden="true" />
        </template>
        <Tooltip>
          <TooltipTrigger as-child>
            <Button
              variant="ghost"
              size="icon"
              class="size-7"
              aria-label="關閉面板"
              @click="ws.setVisible(false)"
            >
              <X class="size-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>關閉面板</TooltipContent>
        </Tooltip>
      </div>
    </TooltipProvider>
  </header>
</template>

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
  Plus,
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
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

const showUpload = caps.data.features.file_upload
const showNew = caps.data.features.session_workspace
const showAddMenu = showUpload || showNew
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
          <!-- + dropdown：上傳檔案 / 上傳資料夾 / 新增檔案 / 新增資料夾 -->
          <DropdownMenu v-if="showAddMenu">
            <DropdownMenuTrigger as-child>
              <Button
                variant="ghost"
                size="icon"
                class="size-7"
                aria-label="新增或上傳"
                title="新增或上傳"
              >
                <Plus class="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" class="w-40">
              <template v-if="caps.data.features.file_upload">
                <DropdownMenuItem @click="openPicker">
                  <Upload class="mr-2 size-3.5" />
                  上傳檔案
                </DropdownMenuItem>
                <DropdownMenuItem @click="openFolderPicker">
                  <FolderUp class="mr-2 size-3.5" />
                  上傳資料夾
                </DropdownMenuItem>
              </template>
              <DropdownMenuSeparator v-if="caps.data.features.file_upload && caps.data.features.session_workspace" />
              <template v-if="caps.data.features.session_workspace">
                <DropdownMenuItem @click="ws.openNewFile()">
                  <FilePlus class="mr-2 size-3.5" />
                  新增檔案
                </DropdownMenuItem>
                <DropdownMenuItem @click="ws.openMkdir()">
                  <FolderPlus class="mr-2 size-3.5" />
                  新增資料夾
                </DropdownMenuItem>
              </template>
            </DropdownMenuContent>
          </DropdownMenu>

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

          <!-- 排序 -->
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

          <!-- 下載 ZIP -->
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

          <!-- 重新整理 -->
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

        <!-- 關閉 -->
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

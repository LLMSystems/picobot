<script setup lang="ts">
import { ref } from 'vue'
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
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useWorkspaceStore } from '@/stores/workspace'
import { useCapabilitiesStore } from '@/stores/capabilities'

const emit = defineEmits<{ (e: 'upload', files: File[]): void }>()

const ws = useWorkspaceStore()
const caps = useCapabilitiesStore()
const fileInputRef = ref<HTMLInputElement | null>(null)

function openPicker() {
  fileInputRef.value?.click()
}

function onFilesChosen(e: Event) {
  const input = e.target as HTMLInputElement
  const list = input.files ? Array.from(input.files) : []
  if (list.length > 0) emit('upload', list)
  input.value = ''
}
</script>

<template>
  <header
    class="flex h-12 shrink-0 items-center gap-2 border-b bg-background px-3"
  >
    <span class="text-sm font-medium">Workspace</span>
    <TooltipProvider :delay-duration="200">
      <div class="ml-auto flex items-center gap-1">
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
        <Tooltip>
          <TooltipTrigger as-child>
            <Button
              variant="ghost"
              size="icon"
              class="size-7"
              aria-label="關閉 workspace"
              @click="ws.setVisible(false)"
            >
              <X class="size-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>關閉 workspace</TooltipContent>
        </Tooltip>
      </div>
    </TooltipProvider>
  </header>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import {
  FolderOpen,
  FolderX,
  AlertTriangle,
  Upload,
  FolderUp,
  FolderPlus,
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { useWorkspaceStore } from '@/stores/workspace'
import { useCapabilitiesStore } from '@/stores/capabilities'

defineProps<{ variant: 'empty' | 'unavailable' | 'error' }>()

const ws = useWorkspaceStore()
const caps = useCapabilitiesStore()
const fileInputRef = ref<HTMLInputElement | null>(null)
const folderInputRef = ref<HTMLInputElement | null>(null)

function openPicker() {
  fileInputRef.value?.click()
}

function openFolderPicker() {
  folderInputRef.value?.click()
}

async function onFilesChosen(e: Event) {
  const input = e.target as HTMLInputElement
  const list = input.files ? Array.from(input.files) : []
  input.value = ''
  if (list.length > 0) await ws.triggerUpload(list, '.')
}
</script>

<template>
  <div
    class="flex flex-1 flex-col items-center justify-center px-4 text-center"
  >
    <template v-if="variant === 'empty'">
      <div
        class="flex w-full max-w-xs flex-col items-center gap-4 rounded-2xl border border-dashed border-border bg-card/40 px-5 py-7"
      >
        <span
          class="flex size-14 items-center justify-center rounded-2xl bg-brand/10 text-brand"
        >
          <FolderOpen class="size-7" />
        </span>
        <div class="space-y-1">
          <p class="text-sm font-medium">Workspace 是空的</p>
          <p class="text-xs leading-relaxed text-muted-foreground">
            拖曳檔案到這裡，或使用下方按鈕開始。
          </p>
        </div>
        <div class="flex w-full flex-col gap-2">
          <Button
            v-if="caps.data.features.file_upload"
            size="sm"
            class="w-full gap-1.5 bg-brand text-brand-foreground hover:bg-brand/90"
            @click="openPicker"
          >
            <Upload class="size-3.5" />
            上傳檔案
          </Button>
          <Button
            v-if="caps.data.features.file_upload"
            size="sm"
            variant="outline"
            class="w-full gap-1.5"
            @click="openFolderPicker"
          >
            <FolderUp class="size-3.5" />
            上傳資料夾
          </Button>
          <Button
            v-if="caps.data.features.session_workspace"
            size="sm"
            variant="outline"
            class="w-full gap-1.5"
            @click="ws.openMkdir('.')"
          >
            <FolderPlus class="size-3.5" />
            新增資料夾
          </Button>
        </div>
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
      </div>
    </template>
    <template v-else-if="variant === 'unavailable'">
      <div class="flex flex-col items-center gap-2 text-xs text-muted-foreground">
        <FolderX class="size-7 opacity-40" />
        <p>此 session 沒有 workspace</p>
      </div>
    </template>
    <template v-else>
      <div class="flex flex-col items-center gap-2 text-xs text-muted-foreground">
        <AlertTriangle class="size-7 opacity-40" />
        <p>無法讀取 workspace</p>
      </div>
    </template>
  </div>
</template>

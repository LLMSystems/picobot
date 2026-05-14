<script setup lang="ts">
import { ref } from 'vue'
import { File as FileIcon, Maximize2 } from 'lucide-vue-next'
import { useWorkspaceStore } from '@/stores/workspace'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import WorkspaceFileBody from './WorkspaceFileBody.vue'

const ws = useWorkspaceStore()
const showFullscreen = ref(false)
</script>

<template>
  <div class="flex h-full flex-col overflow-hidden border-t">
    <div
      v-if="ws.selectedPath"
      class="flex h-9 shrink-0 items-center gap-2 border-b bg-muted/30 px-3 text-xs"
    >
      <FileIcon class="size-3.5 text-muted-foreground" />
      <span class="truncate font-mono">{{ ws.selectedPath }}</span>
      <span
        v-if="ws.fileContent"
        class="ml-auto shrink-0 text-[10px] text-muted-foreground"
      >
        {{ ws.fileContent.line_count }} lines
      </span>
      <Button
        v-if="ws.fileContent || ws.loadingFile || ws.fileError"
        variant="ghost"
        size="icon"
        class="size-6"
        aria-label="全螢幕預覽"
        title="全螢幕預覽"
        @click="showFullscreen = true"
      >
        <Maximize2 class="size-3.5" />
      </Button>
    </div>

    <WorkspaceFileBody class="min-h-0 flex-1" />

    <Dialog v-model:open="showFullscreen">
      <DialogContent
        class="flex h-[85vh] max-h-[85vh] w-[90vw] max-w-[1200px] flex-col gap-0 overflow-hidden p-0 sm:max-w-[90vw]"
      >
        <DialogHeader class="shrink-0 border-b bg-muted/30 px-4 py-2.5">
          <DialogTitle class="flex items-center gap-2 text-sm font-mono">
            <FileIcon class="size-4 text-muted-foreground" />
            <span class="truncate">{{ ws.selectedPath }}</span>
            <span
              v-if="ws.fileContent"
              class="ml-auto pr-8 text-[11px] font-sans text-muted-foreground"
            >
              {{ ws.fileContent.line_count }} lines
            </span>
          </DialogTitle>
        </DialogHeader>
        <WorkspaceFileBody class="min-h-0 flex-1" />
      </DialogContent>
    </Dialog>
  </div>
</template>

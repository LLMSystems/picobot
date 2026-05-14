<script setup lang="ts">
import { computed } from 'vue'
import { File as FileIcon, Loader2 } from 'lucide-vue-next'
import { useWorkspaceStore } from '@/stores/workspace'
import { ApiError } from '@/lib/errors'
import MarkdownView from '@/components/common/MarkdownView.vue'
import { Button } from '@/components/ui/button'

const ws = useWorkspaceStore()

const isMarkdown = computed(() => {
  const p = ws.selectedPath
  if (!p) return false
  const lower = p.toLowerCase()
  return lower.endsWith('.md') || lower.endsWith('.markdown')
})

const errorMessage = computed(() => {
  const e = ws.fileError
  if (!e) return null
  if (e instanceof ApiError) {
    switch (e.code) {
      case 'WORKSPACE_BINARY_FILE_UNSUPPORTED':
        return '此檔為 binary，無法預覽'
      case 'WORKSPACE_FILE_NOT_FOUND':
        return '此檔案已不存在'
      case 'WORKSPACE_NOT_A_FILE':
        return '此路徑不是檔案'
      case 'WORKSPACE_PATH_INVALID':
        return '路徑不合法'
      default:
        return e.message
    }
  }
  return null
})
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
    </div>

    <div class="flex-1 overflow-auto">
      <template v-if="!ws.selectedPath">
        <div class="flex h-full items-center justify-center px-4 text-center text-xs text-muted-foreground">
          點左側檔案以預覽
        </div>
      </template>
      <template v-else-if="ws.loadingFile && !ws.fileContent">
        <div class="flex h-full items-center justify-center gap-2 text-xs text-muted-foreground">
          <Loader2 class="size-4 animate-spin" />
          載入中…
        </div>
      </template>
      <template v-else-if="errorMessage">
        <div class="flex h-full items-center justify-center px-4 text-center text-xs text-muted-foreground">
          {{ errorMessage }}
        </div>
      </template>
      <template v-else-if="ws.fileContent">
        <MarkdownView
          v-if="isMarkdown"
          :content="ws.fileContent.content"
          class="px-4 py-3"
        />
        <pre
          v-else
          class="m-0 whitespace-pre overflow-auto bg-muted/20 px-4 py-3 font-mono text-xs leading-relaxed"
        ><code>{{ ws.fileContent.content }}</code></pre>
      </template>
    </div>

    <div
      v-if="ws.fileContent?.truncated"
      class="flex shrink-0 items-center gap-2 border-t bg-muted/40 px-3 py-2 text-[11px]"
    >
      <span class="text-muted-foreground">已截斷</span>
      <Button
        size="sm"
        variant="outline"
        class="ml-auto h-7 px-2 text-xs"
        @click="ws.loadMoreFile()"
      >
        載入更多
      </Button>
    </div>
  </div>
</template>

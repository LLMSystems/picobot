<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Loader2 } from 'lucide-vue-next'
import { ApiError } from '@/lib/errors'
import { useWorkspaceStore } from '@/stores/workspace'
import MarkdownView from '@/components/common/MarkdownView.vue'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { detectPreviewKind, detectLanguage } from '@/lib/preview'
import { useCodePreviewPrefs } from '@/composables/useCodePreviewPrefs'
import CodeEditor from './CodeEditor.vue'

const ws = useWorkspaceStore()
const { wrap, fontSize } = useCodePreviewPrefs()

type HtmlMode = 'preview' | 'source'
const htmlMode = ref<HtmlMode>('preview')

watch(
  () => ws.selectedPath,
  () => {
    htmlMode.value = 'preview'
  },
)

function htmlTabClass(m: HtmlMode): string {
  const base =
    'inline-flex items-center rounded px-2.5 py-1 text-xs transition-colors'
  return htmlMode.value === m
    ? `${base} bg-background text-foreground shadow-sm`
    : `${base} text-muted-foreground hover:text-foreground`
}

const previewKind = computed(() => detectPreviewKind(ws.selectedPath))

const rawUrl = computed(() => {
  const sid = ws.sessionId
  const p = ws.selectedPath
  if (!sid || !p) return ''
  return api.workspaceFileRawUrl(sid, p)
})

const codeLanguage = computed(() => detectLanguage(ws.selectedPath))

const isMarkdown = computed(() => {
  const p = ws.selectedPath
  if (!p) return false
  const lower = p.toLowerCase()
  return lower.endsWith('.md') || lower.endsWith('.markdown')
})

function onEditUpdate(value: string) {
  ws.editContent = value
}

function onSave() {
  void ws.saveFile()
}

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
  <div class="flex h-full min-h-0 flex-col">
    <!-- 編輯模式 -->
    <CodeEditor
      v-if="ws.editMode"
      class="bg-muted/20"
      editable
      :model-value="ws.editContent"
      :language="codeLanguage"
      :wrap="wrap"
      :font-size="fontSize"
      :on-save="onSave"
      @update:model-value="onEditUpdate"
    />

    <div v-else class="flex min-h-0 flex-1 flex-col overflow-hidden">
      <template v-if="!ws.selectedPath">
        <div class="flex h-full items-center justify-center px-4 text-center text-xs text-muted-foreground">
          點左側檔案以預覽
        </div>
      </template>
      <template v-else-if="previewKind === 'image' || previewKind === 'svg'">
        <div class="flex h-full items-center justify-center bg-muted/20 p-4">
          <img
            :src="rawUrl"
            :alt="ws.selectedPath ?? ''"
            class="max-h-full max-w-full object-contain"
          />
        </div>
      </template>
      <template v-else-if="previewKind === 'pdf'">
        <iframe
          :src="rawUrl"
          :title="ws.selectedPath ?? ''"
          class="h-full w-full border-0 bg-muted/20"
        />
      </template>
      <template v-else-if="previewKind === 'html'">
        <div class="flex h-full min-h-0 flex-col">
          <div
            class="flex shrink-0 items-center gap-1 border-b bg-muted/30 px-2 py-1.5"
            role="tablist"
          >
            <div class="flex items-center gap-0.5 rounded-md border bg-muted/40 p-0.5">
              <button
                type="button"
                role="tab"
                :aria-selected="htmlMode === 'preview'"
                :class="htmlTabClass('preview')"
                @click="htmlMode = 'preview'"
              >
                預覽
              </button>
              <button
                type="button"
                role="tab"
                :aria-selected="htmlMode === 'source'"
                :class="htmlTabClass('source')"
                @click="htmlMode = 'source'"
              >
                原始碼
              </button>
            </div>
          </div>
          <iframe
            v-if="htmlMode === 'preview'"
            :src="rawUrl"
            :title="ws.selectedPath ?? ''"
            sandbox="allow-scripts"
            class="h-full w-full border-0 bg-background"
          />
          <template v-else>
            <template v-if="ws.loadingFile && !ws.fileContent">
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
              <CodeEditor
                class="flex-1 bg-muted/20"
                :model-value="ws.fileContent.content"
                :language="codeLanguage"
                :wrap="wrap"
                :font-size="fontSize"
              />
            </template>
          </template>
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
          class="overflow-auto px-4 py-3"
        />
        <CodeEditor
          v-else
          class="bg-muted/20"
          :model-value="ws.fileContent.content"
          :language="codeLanguage"
          :wrap="wrap"
          :font-size="fontSize"
        />
      </template>
    </div>

    <div
      v-if="!ws.editMode && ws.fileContent?.truncated"
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

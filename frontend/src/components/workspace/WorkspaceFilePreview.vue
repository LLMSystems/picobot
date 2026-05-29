<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  File as FileIcon,
  Maximize2,
  Copy,
  X,
  Download,
  Pencil,
  Save,
  XCircle,
  WrapText,
  Minus,
  Plus,
} from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import { useWorkspaceStore } from '@/stores/workspace'
import { detectPreviewKind, detectLanguage, languageLabel } from '@/lib/preview'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import WorkspaceFileBody from './WorkspaceFileBody.vue'
import { useCodePreviewPrefs } from '@/composables/useCodePreviewPrefs'

const ws = useWorkspaceStore()
const showFullscreen = ref(false)
const { wrap, fontSize, toggleWrap, bumpSize } = useCodePreviewPrefs()

const previewKind = computed(() => detectPreviewKind(ws.selectedPath))
const isBinaryPreview = computed(() => previewKind.value !== 'text')
const isTextFile = computed(() => previewKind.value === 'text' || previewKind.value === 'html')
const showCodeControls = computed(
  () => isTextFile.value && ws.fileContent !== null,
)
const langBadge = computed(() => languageLabel(detectLanguage(ws.selectedPath)))
const canShrink = computed(() => fontSize.value !== 'sm')
const canGrow = computed(() => fontSize.value !== 'lg')
const hasAnything = computed(
  () =>
    isBinaryPreview.value ||
    ws.fileContent !== null ||
    ws.loadingFile ||
    ws.fileError !== null,
)

async function copyContent() {
  const text = ws.fileContent?.content
  if (text === undefined) return
  try {
    await navigator.clipboard.writeText(text)
    toast.success('已複製檔案內容')
  } catch {
    toast.error('複製失敗')
  }
}

function downloadFile() {
  const id = ws.sessionId
  const path = ws.selectedPath
  if (!id || !path) return
  const base = api.workspaceFileRawUrl(id, path)
  const url = `${base}&download=true`
  const a = document.createElement('a')
  a.href = url
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}
</script>

<template>
  <div class="flex h-full flex-col overflow-hidden border-t">
    <div
      v-if="ws.selectedPath"
      class="flex h-9 shrink-0 items-center gap-2 border-b bg-muted/30 px-3 text-xs"
    >
      <FileIcon class="size-3.5 text-muted-foreground" />
      <span class="truncate font-mono">{{ ws.selectedPath }}</span>

      <!-- 編輯模式：wrap / 字級 / 儲存 / 取消 -->
      <template v-if="ws.editMode">
        <span class="ml-auto shrink-0 text-[10px] text-amber-500">編輯中</span>
        <template v-if="showCodeControls">
          <Button
            variant="ghost"
            size="icon"
            class="size-6"
            :aria-label="wrap ? '關閉自動換行' : '開啟自動換行'"
            :title="wrap ? '關閉自動換行' : '開啟自動換行'"
            :class="wrap ? 'text-primary' : ''"
            @click="toggleWrap"
          >
            <WrapText class="size-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            class="size-6"
            aria-label="縮小字體"
            title="縮小字體"
            :disabled="!canShrink"
            @click="bumpSize(-1)"
          >
            <Minus class="size-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            class="size-6"
            aria-label="放大字體"
            title="放大字體"
            :disabled="!canGrow"
            @click="bumpSize(1)"
          >
            <Plus class="size-3.5" />
          </Button>
        </template>
        <Button
          variant="ghost"
          size="icon"
          class="size-6"
          aria-label="儲存"
          title="儲存 (Ctrl+S)"
          :disabled="ws.editSaving"
          @click="ws.saveFile()"
        >
          <Save class="size-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          class="size-6"
          aria-label="取消編輯"
          title="取消編輯"
          @click="ws.exitEditMode()"
        >
          <XCircle class="size-3.5" />
        </Button>
      </template>

      <!-- 一般模式 -->
      <template v-else>
        <span
          v-if="langBadge"
          class="ml-auto shrink-0 rounded border border-border/60 bg-muted/40 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground"
        >
          {{ langBadge }}
        </span>
        <span
          v-if="ws.fileContent"
          :class="[
            'shrink-0 text-[10px] text-muted-foreground',
            langBadge ? '' : 'ml-auto',
          ]"
        >
          {{ ws.fileContent.line_count }} lines
        </span>
        <template v-if="showCodeControls">
          <Button
            variant="ghost"
            size="icon"
            class="size-6"
            :aria-label="wrap ? '關閉自動換行' : '開啟自動換行'"
            :title="wrap ? '關閉自動換行' : '開啟自動換行'"
            :class="wrap ? 'text-primary' : ''"
            @click="toggleWrap"
          >
            <WrapText class="size-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            class="size-6"
            aria-label="縮小字體"
            title="縮小字體"
            :disabled="!canShrink"
            @click="bumpSize(-1)"
          >
            <Minus class="size-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            class="size-6"
            aria-label="放大字體"
            title="放大字體"
            :disabled="!canGrow"
            @click="bumpSize(1)"
          >
            <Plus class="size-3.5" />
          </Button>
        </template>
        <Button
          v-if="ws.fileContent && isTextFile"
          variant="ghost"
          size="icon"
          class="size-6"
          aria-label="編輯檔案"
          title="編輯檔案"
          @click="ws.enterEditMode()"
        >
          <Pencil class="size-3.5" />
        </Button>
        <Button
          v-if="ws.fileContent"
          variant="ghost"
          size="icon"
          class="size-6"
          aria-label="複製檔案內容"
          title="複製檔案內容"
          @click="copyContent"
        >
          <Copy class="size-3.5" />
        </Button>
        <Button
          v-if="ws.selectedPath"
          variant="ghost"
          size="icon"
          class="size-6"
          aria-label="下載檔案"
          title="下載檔案"
          @click="downloadFile"
        >
          <Download class="size-3.5" />
        </Button>
        <Button
          v-if="hasAnything"
          variant="ghost"
          size="icon"
          class="size-6"
          aria-label="全螢幕預覽"
          title="全螢幕預覽"
          @click="showFullscreen = true"
        >
          <Maximize2 class="size-3.5" />
        </Button>
      </template>

      <Button
        variant="ghost"
        size="icon"
        class="size-6"
        aria-label="關閉預覽"
        title="關閉預覽"
        @click="ws.select(null)"
      >
        <X class="size-3.5" />
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
            <div class="ml-auto flex items-center gap-1 pr-8">
              <template v-if="ws.editMode">
                <span class="shrink-0 font-sans text-[11px] text-amber-500">編輯中</span>
                <template v-if="showCodeControls">
                  <Button
                    variant="ghost"
                    size="icon"
                    class="size-7"
                    :aria-label="wrap ? '關閉自動換行' : '開啟自動換行'"
                    :title="wrap ? '關閉自動換行' : '開啟自動換行'"
                    :class="wrap ? 'text-primary' : ''"
                    @click="toggleWrap"
                  >
                    <WrapText class="size-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    class="size-7"
                    aria-label="縮小字體"
                    title="縮小字體"
                    :disabled="!canShrink"
                    @click="bumpSize(-1)"
                  >
                    <Minus class="size-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    class="size-7"
                    aria-label="放大字體"
                    title="放大字體"
                    :disabled="!canGrow"
                    @click="bumpSize(1)"
                  >
                    <Plus class="size-3.5" />
                  </Button>
                </template>
                <Button
                  variant="ghost"
                  size="icon"
                  class="size-7"
                  aria-label="儲存"
                  title="儲存 (Ctrl+S)"
                  :disabled="ws.editSaving"
                  @click="ws.saveFile()"
                >
                  <Save class="size-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  class="size-7"
                  aria-label="取消編輯"
                  title="取消編輯"
                  @click="ws.exitEditMode()"
                >
                  <XCircle class="size-3.5" />
                </Button>
              </template>
              <template v-else>
                <span
                  v-if="langBadge"
                  class="rounded border border-border/60 bg-muted/40 px-1.5 py-0.5 text-[10px] font-sans font-medium text-muted-foreground"
                >
                  {{ langBadge }}
                </span>
                <span
                  v-if="ws.fileContent"
                  class="text-[11px] font-sans text-muted-foreground"
                >
                  {{ ws.fileContent.line_count }} lines
                </span>
                <template v-if="showCodeControls">
                  <Button
                    variant="ghost"
                    size="icon"
                    class="size-7"
                    :aria-label="wrap ? '關閉自動換行' : '開啟自動換行'"
                    :title="wrap ? '關閉自動換行' : '開啟自動換行'"
                    :class="wrap ? 'text-primary' : ''"
                    @click="toggleWrap"
                  >
                    <WrapText class="size-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    class="size-7"
                    aria-label="縮小字體"
                    title="縮小字體"
                    :disabled="!canShrink"
                    @click="bumpSize(-1)"
                  >
                    <Minus class="size-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    class="size-7"
                    aria-label="放大字體"
                    title="放大字體"
                    :disabled="!canGrow"
                    @click="bumpSize(1)"
                  >
                    <Plus class="size-3.5" />
                  </Button>
                </template>
                <Button
                  v-if="ws.fileContent && isTextFile"
                  variant="ghost"
                  size="icon"
                  class="size-7"
                  aria-label="編輯檔案"
                  title="編輯檔案"
                  @click="ws.enterEditMode()"
                >
                  <Pencil class="size-3.5" />
                </Button>
                <Button
                  v-if="ws.fileContent"
                  variant="ghost"
                  size="icon"
                  class="size-7"
                  aria-label="複製檔案內容"
                  title="複製檔案內容"
                  @click="copyContent"
                >
                  <Copy class="size-3.5" />
                </Button>
              </template>
            </div>
          </DialogTitle>
        </DialogHeader>
        <WorkspaceFileBody class="min-h-0 flex-1" />
      </DialogContent>
    </Dialog>
  </div>
</template>

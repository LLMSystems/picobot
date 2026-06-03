<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { Send, Square, Plus, X, Loader2, AlertTriangle, FileText } from 'lucide-vue-next'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useChatStore } from '@/stores/chat'
import { useCapabilitiesStore } from '@/stores/capabilities'
import { useComposerBus } from '@/composables/useComposerBus'
import { useImageAttachments, ACCEPTED_FILE_EXTENSIONS } from '@/composables/useImageAttachments'
import { useSelectedModel } from '@/composables/useSelectedModel'
import ModelSelector from './ModelSelector.vue'
import TodoChip from './TodoChip.vue'
import { ApiError } from '@/lib/errors'
import { api } from '@/lib/api'
import { toast } from 'vue-sonner'

const chat = useChatStore()
const caps = useCapabilitiesStore()
const bus = useComposerBus()

const text = ref('')
const isComposing = ref(false)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const isDragOver = ref(false)
let dragCounter = 0

const imagesEnabled = computed(
  () =>
    caps.data.features.multimodal && caps.data.features.session_workspace,
)

const fileUploadEnabled = computed(() => caps.data.features.session_workspace)

const WORKSPACE_DRAG_TYPE = 'application/x-picobot-path'

function insertPathIntoText(path: string) {
  const el = textareaRef.value
  const pos = el?.selectionStart ?? text.value.length
  const before = text.value.slice(0, pos)
  const after = text.value.slice(pos)
  const needsLeadingSpace = before.length > 0 && !/\s$/.test(before)
  const needsTrailingSpace = after.length > 0 && !/^\s/.test(after)
  const inserted = `${needsLeadingSpace ? ' ' : ''}@${path}${needsTrailingSpace ? ' ' : ' '}`
  text.value = `${before}${inserted}${after}`
  void nextTick().then(() => {
    if (el) {
      const newPos = before.length + inserted.length
      el.focus()
      el.setSelectionRange(newPos, newPos)
    }
    autoResize()
  })
}

function removePathFromText(path: string) {
  const mention = `@${path}`
  // Remove the mention and any surrounding whitespace padding we may have added
  text.value = text.value
    .replace(new RegExp(`\\s*${mention.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*`, 'g'), ' ')
    .trim()
  void nextTick().then(autoResize)
}

const attachments = useImageAttachments(
  () => chat.currentSessionId,
  (path) => insertPathIntoText(path),
  (path) => removePathFromText(path),
)
const { selected: selectedModel, resetToDefault: resetModel } =
  useSelectedModel()

const dragKind = ref<'files' | 'workspace' | null>(null)

interface MentionFile {
  path: string
  name: string
}
const mentionFiles = ref<MentionFile[]>([])
const mentionFilesLoadedFor = ref<string | null>(null)
const mentionActive = ref(false)
const mentionQuery = ref('')
const mentionStart = ref(0)
const mentionSelected = ref(0)

const filteredMentionFiles = computed<MentionFile[]>(() => {
  if (!mentionActive.value) return []
  const q = mentionQuery.value.toLowerCase()
  const all = mentionFiles.value
  const list = q
    ? all.filter((f) => f.path.toLowerCase().includes(q))
    : all
  return list.slice(0, 8)
})

watch(filteredMentionFiles, () => {
  mentionSelected.value = 0
})

async function loadMentionFiles() {
  const sid = chat.currentSessionId
  if (!sid) return
  if (mentionFilesLoadedFor.value === sid) return
  try {
    const resp = await api.listWorkspaceTree(sid, {
      recursive: true,
      max_entries: 500,
    })
    mentionFiles.value = resp.entries
      .filter((e) => e.type === 'file')
      .map((e) => ({ path: e.path, name: e.name }))
    mentionFilesLoadedFor.value = sid
  } catch {
    // silently ignore - mention popover just won't show files
  }
}

watch(
  () => chat.currentSessionId,
  (sid) => {
    if (sid !== mentionFilesLoadedFor.value) {
      mentionFiles.value = []
      mentionFilesLoadedFor.value = null
      mentionActive.value = false
    }
  },
)

function closeMention() {
  mentionActive.value = false
  mentionQuery.value = ''
}

function checkMention() {
  const el = textareaRef.value
  if (!el) {
    closeMention()
    return
  }
  const pos = el.selectionStart ?? text.value.length
  const before = text.value.slice(0, pos)
  const lastAt = before.lastIndexOf('@')
  if (lastAt < 0) {
    closeMention()
    return
  }
  const prevChar = lastAt > 0 ? text.value[lastAt - 1] : ''
  if (prevChar && !/\s/.test(prevChar)) {
    closeMention()
    return
  }
  const query = before.slice(lastAt + 1)
  if (/\s/.test(query)) {
    closeMention()
    return
  }
  mentionStart.value = lastAt
  mentionQuery.value = query
  mentionActive.value = true
  void loadMentionFiles()
}

async function insertMention(file: MentionFile) {
  const el = textareaRef.value
  if (!el) return
  const pos = el.selectionStart ?? text.value.length
  const before = text.value.slice(0, mentionStart.value)
  const after = text.value.slice(pos)
  const inserted = `@${file.path} `
  text.value = `${before}${inserted}${after}`
  closeMention()
  await nextTick()
  const newPos = before.length + inserted.length
  el.focus()
  el.setSelectionRange(newPos, newPos)
  autoResize()
}

const canSend = computed(() => {
  if (chat.isStreaming || chat.currentSessionId === null) return false
  if (attachments.hasUploading.value) return false
  const hasText = text.value.trim().length > 0
  return hasText || attachments.hasReady.value
})

const placeholder = computed(() =>
  chat.currentSessionId
    ? '問 Picobot 一個問題，或請它操作 workspace…'
    : '請先選擇或建立對話',
)

function autoResize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  const next = Math.min(el.scrollHeight, 240)
  el.style.height = `${next}px`
}

watch(text, () => {
  void nextTick().then(autoResize)
})

watch(
  () => bus.focusToken.value,
  async () => {
    const { text: filled, submit, mode } = bus.consume()
    if (filled !== null) {
      if (mode === 'append' && text.value) {
        const sep = text.value.endsWith('\n') ? '' : '\n'
        text.value = `${text.value}${sep}${filled}`
      } else {
        text.value = filled
      }
    }
    await nextTick()
    const el = textareaRef.value
    el?.focus()
    if (el && filled !== null) {
      const end = el.value.length
      el.setSelectionRange(end, end)
    }
    autoResize()
    if (submit && filled !== null && canSend.value) {
      void send()
    }
  },
  { immediate: true },
)

async function send() {
  if (!canSend.value) return
  const t = text.value
  const imgs = attachments.toImages()
  const model = selectedModel.value
  text.value = ''
  attachments.clearAll()
  await nextTick()
  autoResize()
  try {
    await chat.send(t, imgs, model)
  } catch (err) {
    if (err instanceof ApiError && err.code === 'MODEL_NOT_ALLOWED') {
      toast.error('所選模型不在允許清單', {
        description: '已重設為預設模型，請再試一次',
      })
      resetModel()
      void caps.refresh()
      return
    }
    if (err instanceof Error) {
      toast.error('傳送失敗', {
        description: err.message,
      })
    }
  }
}

function onKeydown(e: KeyboardEvent) {
  if (isComposing.value || e.keyCode === 229) return

  if (mentionActive.value && filteredMentionFiles.value.length > 0) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      mentionSelected.value =
        (mentionSelected.value + 1) % filteredMentionFiles.value.length
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      const len = filteredMentionFiles.value.length
      mentionSelected.value = (mentionSelected.value - 1 + len) % len
      return
    }
    if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault()
      const chosen = filteredMentionFiles.value[mentionSelected.value]
      if (chosen) void insertMention(chosen)
      return
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      closeMention()
      return
    }
  }

  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    if (chat.isStreaming) return
    void send()
    return
  }
  if (e.key === 'Escape') {
    if (chat.isStreaming) {
      chat.stop()
    } else if (text.value) {
      text.value = ''
    }
    return
  }
  if (e.key === 'ArrowUp' && text.value === '') {
    const last = chat.retryLastUser()
    if (last) {
      e.preventDefault()
      text.value = last
    }
  }
}

function onInput() {
  autoResize()
  checkMention()
}

function stop() {
  chat.stop()
}

function openPicker() {
  if (!imagesEnabled.value && !fileUploadEnabled.value) return
  fileInputRef.value?.click()
}

function onFilesChosen(e: Event) {
  const input = e.target as HTMLInputElement
  const list = input.files ? Array.from(input.files) : []
  if (list.length > 0) attachments.addFiles(list)
  input.value = ''
}

function onPaste(e: ClipboardEvent) {
  if (!imagesEnabled.value) return
  attachments.handlePaste(e)
}

function detectDragKind(e: DragEvent): 'files' | 'workspace' | null {
  const types = e.dataTransfer?.types
  if (!types) return null
  if (types.includes(WORKSPACE_DRAG_TYPE)) return 'workspace'
  if ((imagesEnabled.value || fileUploadEnabled.value) && types.includes('Files')) return 'files'
  return null
}

function onDragEnter(e: DragEvent) {
  const kind = detectDragKind(e)
  if (!kind) return
  dragCounter += 1
  isDragOver.value = true
  dragKind.value = kind
}

function onDragLeave() {
  dragCounter = Math.max(0, dragCounter - 1)
  if (dragCounter === 0) {
    isDragOver.value = false
    dragKind.value = null
  }
}

function onDragOver(e: DragEvent) {
  const kind = detectDragKind(e)
  if (!kind) return
  e.preventDefault()
  if (e.dataTransfer) {
    e.dataTransfer.dropEffect = kind === 'workspace' ? 'move' : 'copy'
  }
}

async function insertWorkspacePath(path: string) {
  const el = textareaRef.value
  const pos = el?.selectionStart ?? text.value.length
  const before = text.value.slice(0, pos)
  const after = text.value.slice(pos)
  const needsLeadingSpace =
    before.length > 0 && !/\s$/.test(before)
  const needsTrailingSpace = after.length > 0 && !/^\s/.test(after)
  const inserted = `${needsLeadingSpace ? ' ' : ''}@${path}${needsTrailingSpace ? ' ' : ' '}`
  text.value = `${before}${inserted}${after}`
  await nextTick()
  if (el) {
    const newPos = before.length + inserted.length
    el.focus()
    el.setSelectionRange(newPos, newPos)
  }
  autoResize()
}

function onDrop(e: DragEvent) {
  dragCounter = 0
  isDragOver.value = false
  const wsPath = e.dataTransfer?.getData(WORKSPACE_DRAG_TYPE)
  if (wsPath) {
    e.preventDefault()
    dragKind.value = null
    void insertWorkspacePath(wsPath)
    return
  }
  dragKind.value = null
  if (!imagesEnabled.value && !fileUploadEnabled.value) return
  attachments.handleDrop(e)
}

// Build the accept string for the file input
const fileInputAccept = computed(() => {
  const parts: string[] = []
  if (imagesEnabled.value) parts.push('image/*')
  if (fileUploadEnabled.value) parts.push(...ACCEPTED_FILE_EXTENSIONS)
  return parts.join(',')
})

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
</script>

<template>
  <div class="bg-muted/30 pb-3 pt-3">
    <div class="mx-auto w-full max-w-3xl px-4">
      <div class="mb-1.5 flex justify-end">
        <TodoChip />
      </div>
      <div
        class="dark relative rounded-2xl border bg-card text-foreground px-4 py-3 shadow-md transition-shadow focus-within:border-brand/40 focus-within:shadow-lg focus-within:ring-2 focus-within:ring-brand/20"
        :class="
          isDragOver
            ? 'border-brand/60 ring-2 ring-brand/30'
            : ''
        "
        @dragenter="onDragEnter"
        @dragleave="onDragLeave"
        @dragover="onDragOver"
        @drop="onDrop"
      >
        <!-- Attachment chips -->
        <div
          v-if="attachments.attachments.value.length > 0"
          class="mb-2 flex flex-wrap gap-2"
        >
          <!-- Image chips -->
          <div
            v-for="att in attachments.imageAttachments.value"
            :key="att.id"
            class="group relative size-20 overflow-hidden rounded-lg border bg-muted"
          >
            <img
              :src="att.previewUrl"
              :alt="att.file.name"
              class="size-full object-cover"
              :class="att.status !== 'ready' ? 'opacity-50' : ''"
            />
            <div
              v-if="att.status === 'uploading'"
              class="absolute inset-0 flex items-center justify-center bg-black/30"
            >
              <Loader2 class="size-5 animate-spin text-white" />
            </div>
            <button
              v-if="att.status === 'error'"
              type="button"
              class="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-destructive/70 text-[10px] text-white"
              :title="att.error || '上傳失敗，點擊重試'"
              @click="attachments.retry(att.id)"
            >
              <AlertTriangle class="size-4" />
              <span>重試</span>
            </button>
            <button
              type="button"
              class="absolute right-1 top-1 grid size-5 place-items-center rounded-full bg-black/70 text-white opacity-0 transition-opacity hover:bg-black group-hover:opacity-100"
              aria-label="移除"
              @click.stop="attachments.remove(att.id)"
            >
              <X class="size-3" />
            </button>
          </div>

          <!-- File chips -->
          <div
            v-for="att in attachments.fileAttachments.value"
            :key="att.id"
            class="group relative flex max-w-[180px] items-center gap-2 rounded-lg border bg-muted px-3 py-2 text-xs"
            :class="att.status === 'error' ? 'border-destructive/50' : ''"
          >
            <div class="shrink-0">
              <Loader2
                v-if="att.status === 'uploading'"
                class="size-4 animate-spin text-muted-foreground"
              />
              <AlertTriangle
                v-else-if="att.status === 'error'"
                class="size-4 text-destructive"
              />
              <FileText
                v-else
                class="size-4 text-muted-foreground"
              />
            </div>
            <div class="min-w-0 flex-1">
              <p class="truncate font-medium leading-tight" :title="att.file.name">
                {{ att.file.name }}
              </p>
              <p
                v-if="att.status === 'error'"
                class="truncate text-[10px] text-destructive"
                :title="att.error"
              >
                {{ att.error || '上傳失敗' }}
              </p>
              <p v-else class="text-[10px] text-muted-foreground">
                {{ formatFileSize(att.file.size) }}
              </p>
            </div>
            <button
              v-if="att.status === 'error'"
              type="button"
              class="shrink-0 text-[10px] text-muted-foreground underline hover:text-foreground"
              @click.stop="attachments.retry(att.id)"
            >
              重試
            </button>
            <button
              type="button"
              class="absolute right-1 top-1 grid size-4 place-items-center rounded-full bg-muted-foreground/20 text-muted-foreground opacity-0 transition-opacity hover:bg-muted-foreground/40 group-hover:opacity-100"
              aria-label="移除"
              @click.stop="attachments.remove(att.id)"
            >
              <X class="size-2.5" />
            </button>
          </div>
        </div>

        <!-- 終端機風格輸入區：綠色 > 提示符 + 等寬字 + 綠色游標，呼應 icon 螢幕 -->
        <div class="flex items-start gap-1.5">
          <span
            class="shrink-0 select-none font-mono text-sm font-semibold leading-7 text-brand"
            aria-hidden="true"
          >&gt;</span>
          <textarea
            ref="textareaRef"
            v-model="text"
            rows="1"
            :placeholder="placeholder"
            :disabled="chat.currentSessionId === null"
            class="block max-h-60 min-h-[1.75rem] w-full resize-none bg-transparent font-mono text-sm leading-7 text-foreground caret-brand outline-none placeholder:text-muted-foreground"
            @keydown="onKeydown"
            @paste="onPaste"
            @compositionstart="isComposing = true"
            @compositionend="isComposing = false"
            @input="onInput"
            @click="checkMention"
            @keyup="checkMention"
          />
        </div>

        <div class="mt-1 flex items-center gap-1">
          <TooltipProvider v-if="imagesEnabled || fileUploadEnabled" :delay-duration="200">
            <Tooltip>
              <TooltipTrigger as-child>
                <Button
                  variant="ghost"
                  size="icon"
                  class="size-8 rounded-full"
                  :disabled="
                    chat.currentSessionId === null ||
                    !attachments.canAddMore.value
                  "
                  aria-label="附加檔案"
                  @click="openPicker"
                >
                  <Plus class="size-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top">
                {{ imagesEnabled ? '附加圖片或檔案（拖曳 / 貼上 / 點擊）' : '附加檔案（拖曳 / 點擊）' }}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <input
            v-if="imagesEnabled || fileUploadEnabled"
            ref="fileInputRef"
            type="file"
            :accept="fileInputAccept"
            multiple
            class="hidden"
            @change="onFilesChosen"
          />
          <ModelSelector />
          <div class="flex-1" />
          <Button
            v-if="!chat.isStreaming"
            size="icon"
            class="size-9 rounded-full bg-brand text-brand-foreground shadow-sm transition-transform hover:bg-brand/90 hover:scale-105 disabled:bg-muted disabled:text-muted-foreground disabled:shadow-none disabled:hover:scale-100"
            :disabled="!canSend"
            aria-label="送出"
            @click="send"
          >
            <Send class="size-4" />
          </Button>
          <Button
            v-else
            size="icon"
            variant="destructive"
            class="size-9 rounded-full shadow-sm"
            aria-label="停止"
            @click="stop"
          >
            <Square class="size-4" />
          </Button>
        </div>

        <div
          v-if="isDragOver"
          class="pointer-events-none absolute inset-0 flex items-center justify-center rounded-2xl border-2 border-dashed border-brand/60 bg-background/80 text-sm font-medium text-brand"
        >
          {{
            dragKind === 'workspace'
              ? '放開以引用此檔案'
              : '放開以附加檔案'
          }}
        </div>

        <div
          v-if="mentionActive && filteredMentionFiles.length > 0"
          class="absolute bottom-full left-0 right-0 z-20 mb-2 max-h-64 overflow-y-auto rounded-xl border bg-background shadow-lg"
        >
          <div
            class="flex items-center justify-between gap-2 border-b px-3 py-1.5 text-[11px] text-muted-foreground"
          >
            <span>引用 workspace 檔案</span>
            <span class="font-mono">@{{ mentionQuery || '…' }}</span>
          </div>
          <ul role="listbox" class="py-1">
            <li
              v-for="(f, idx) in filteredMentionFiles"
              :key="f.path"
              role="option"
              :aria-selected="idx === mentionSelected"
              class="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm"
              :class="
                idx === mentionSelected ? 'bg-muted text-foreground' : ''
              "
              @mousedown.prevent="insertMention(f)"
              @mouseenter="mentionSelected = idx"
            >
              <FileText class="size-3.5 shrink-0 text-muted-foreground" />
              <span class="flex-1 truncate font-mono text-xs">{{ f.path }}</span>
            </li>
          </ul>
        </div>
        <div
          v-else-if="mentionActive"
          class="absolute bottom-full left-0 right-0 z-20 mb-2 rounded-xl border bg-background px-3 py-2 text-xs text-muted-foreground shadow-lg"
        >
          找不到符合「{{ mentionQuery }}」的檔案
        </div>
      </div>
      <p class="mt-2 text-center text-[11px] text-muted-foreground/70">
        Enter 送出・Shift+Enter 換行・拖曳 / 貼上 / 點 + 可附加圖片或檔案
      </p>
    </div>
  </div>
</template>

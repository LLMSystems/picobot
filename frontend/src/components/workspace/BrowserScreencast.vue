<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  Loader2,
  RefreshCw,
  MonitorOff,
  AlertTriangle,
  MousePointerClick,
  MousePointer,
  Maximize2,
  ArrowLeft,
  ArrowRight,
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { useBrowserScreencast } from '@/composables/useBrowserScreencast'
import { virtualKeyCodeFor, textForKey } from '@/lib/browserKeymap'

const {
  status,
  frameDataUrl,
  errorMessage,
  fps,
  metadata,
  connect,
  disconnect,
  sendInput,
  navigate,
} = useBrowserScreencast()

const fullscreenOpen = ref(false)
const interactive = ref(true)
const imgRef = ref<HTMLImageElement | null>(null)
const overlayRef = ref<HTMLTextAreaElement | null>(null)
const isComposing = ref(false)

let pendingMoveX = 0
let pendingMoveY = 0
let moveFrame: number | null = null

const statusLabel = computed(() => {
  switch (status.value) {
    case 'idle':
      return '尚未連線'
    case 'checking':
      return '檢查 Chrome 狀態…'
    case 'connecting':
      return '連線中…'
    case 'live':
      return `LIVE · ${fps.value} fps`
    case 'chrome_offline':
      return 'Chrome 未啟動'
    case 'error':
      return errorMessage.value ?? '連線失敗'
  }
  return ''
})

const statusDotClass = computed(() => {
  switch (status.value) {
    case 'live':
      return 'bg-emerald-500 animate-pulse'
    case 'connecting':
    case 'checking':
      return 'bg-amber-500'
    case 'error':
    case 'chrome_offline':
      return 'bg-destructive'
    default:
      return 'bg-muted-foreground/40'
  }
})

const resolutionLabel = computed(() => {
  const m = metadata.value
  if (!m || !m.deviceWidth || !m.deviceHeight) return ''
  return `${m.deviceWidth}×${m.deviceHeight}`
})

function reconnect() {
  void connect()
}

function toggleInteractive() {
  interactive.value = !interactive.value
}

function toChrome(e: MouseEvent | WheelEvent): { x: number; y: number } | null {
  const img = imgRef.value
  if (!img) return null
  const rect = img.getBoundingClientRect()
  if (rect.width <= 0 || rect.height <= 0) return null
  const m = metadata.value
  const dw = m?.deviceWidth ?? rect.width
  const dh = m?.deviceHeight ?? rect.height
  const x = ((e.clientX - rect.left) * dw) / rect.width
  const y = ((e.clientY - rect.top) * dh) / rect.height
  return { x, y }
}

function buttonName(e: MouseEvent): 'left' | 'middle' | 'right' {
  if (e.button === 1) return 'middle'
  if (e.button === 2) return 'right'
  return 'left'
}

function modifiersOf(e: MouseEvent | KeyboardEvent | WheelEvent): number {
  return (
    (e.altKey ? 1 : 0) |
    (e.ctrlKey ? 2 : 0) |
    (e.metaKey ? 4 : 0) |
    (e.shiftKey ? 8 : 0)
  )
}

function onMouseDown(e: MouseEvent) {
  if (!interactive.value || status.value !== 'live') return
  e.preventDefault()
  overlayRef.value?.focus()
  const pt = toChrome(e)
  if (!pt) return
  sendInput({
    event: 'mousedown',
    x: pt.x,
    y: pt.y,
    button: buttonName(e),
    clickCount: e.detail || 1,
    modifiers: modifiersOf(e),
  })
}

function onMouseUp(e: MouseEvent) {
  if (!interactive.value || status.value !== 'live') return
  e.preventDefault()
  const pt = toChrome(e)
  if (!pt) return
  sendInput({
    event: 'mouseup',
    x: pt.x,
    y: pt.y,
    button: buttonName(e),
    clickCount: e.detail || 1,
    modifiers: modifiersOf(e),
  })
}

function onMouseMove(e: MouseEvent) {
  if (!interactive.value || status.value !== 'live') return
  const pt = toChrome(e)
  if (!pt) return
  pendingMoveX = pt.x
  pendingMoveY = pt.y
  if (moveFrame !== null) return
  moveFrame = window.requestAnimationFrame(() => {
    moveFrame = null
    sendInput({ event: 'mousemove', x: pendingMoveX, y: pendingMoveY })
  })
}

function onWheel(e: WheelEvent) {
  if (!interactive.value || status.value !== 'live') return
  e.preventDefault()
  const pt = toChrome(e)
  if (!pt) return
  sendInput({
    event: 'wheel',
    x: pt.x,
    y: pt.y,
    deltaX: e.deltaX,
    deltaY: e.deltaY,
    modifiers: modifiersOf(e),
  })
}

function onContextMenu(e: MouseEvent) {
  if (interactive.value) e.preventDefault()
}

function onKeydown(e: KeyboardEvent) {
  if (!interactive.value || status.value !== 'live') return
  // While IME is composing, let the textarea + browser handle the keystrokes;
  // we'll forward the final result via compositionend.
  if (e.isComposing || isComposing.value || e.key === 'Process') return
  // Avoid swallowing dev-tools / browser-level shortcuts users may need.
  if (e.key === 'F5' || (e.key === 'r' && (e.ctrlKey || e.metaKey))) return
  e.preventDefault()
  const vk = virtualKeyCodeFor(e)
  const text = textForKey(e)
  sendInput({
    event: 'keydown',
    key: e.key,
    code: e.code,
    modifiers: modifiersOf(e),
    ...(vk !== undefined ? { windowsVirtualKeyCode: vk } : {}),
    ...(text !== undefined ? { text } : {}),
  })
  if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
    sendInput({ event: 'keychar', text: e.key })
  }
}

function onKeyup(e: KeyboardEvent) {
  if (!interactive.value || status.value !== 'live') return
  if (e.isComposing || isComposing.value || e.key === 'Process') return
  if (e.key === 'F5' || (e.key === 'r' && (e.ctrlKey || e.metaKey))) return
  e.preventDefault()
  const vk = virtualKeyCodeFor(e)
  sendInput({
    event: 'keyup',
    key: e.key,
    code: e.code,
    modifiers: modifiersOf(e),
    ...(vk !== undefined ? { windowsVirtualKeyCode: vk } : {}),
  })
}

function onCompositionStart() {
  isComposing.value = true
}

function onCompositionEnd(e: CompositionEvent) {
  isComposing.value = false
  const text = e.data
  if (text) sendInput({ event: 'insertText', text })
  // Always clear so the invisible textarea doesn't accumulate state.
  if (overlayRef.value) overlayRef.value.value = ''
}

function onOverlayInput(e: Event) {
  // Keep the invisible textarea empty. Latin chars go through keydown→keychar;
  // CJK characters are delivered via compositionend → insertText. We don't want
  // the textarea to hold stale value.
  if (isComposing.value) return
  const ta = e.target as HTMLTextAreaElement
  ta.value = ''
}

const urlInput = ref('')

function submitUrl() {
  const url = urlInput.value.trim()
  if (!url) return
  navigate({ action: 'goto', url })
}

function goBack() {
  navigate({ action: 'back' })
}

function goForward() {
  navigate({ action: 'forward' })
}

function reloadPage(hard = false) {
  navigate({ action: 'reload', hard })
}

function openFullscreen() {
  fullscreenOpen.value = true
}

onMounted(() => {
  void connect()
})

defineExpose({ disconnect })
</script>

<template>
  <div class="flex h-full min-h-0 flex-col bg-background">
    <div
      class="flex h-9 shrink-0 items-center gap-2 border-b bg-muted/30 px-3 text-xs"
    >
      <span
        class="inline-block size-2 rounded-full"
        :class="statusDotClass"
        aria-hidden="true"
      />
      <span class="font-medium">{{ statusLabel }}</span>
      <span v-if="resolutionLabel" class="text-muted-foreground">
        · {{ resolutionLabel }}
      </span>

      <div class="ml-auto flex items-center gap-1">
        <Button
          v-if="status === 'live'"
          size="sm"
          variant="ghost"
          class="h-6 px-2 text-xs"
          :title="interactive ? '互動模式：開（點擊切換為僅檢視）' : '僅檢視（點擊切換為互動模式）'"
          @click="toggleInteractive"
        >
          <MousePointerClick v-if="interactive" class="mr-1 size-3 text-emerald-500" />
          <MousePointer v-else class="mr-1 size-3" />
          {{ interactive ? '互動中' : '僅檢視' }}
        </Button>
        <Button
          v-if="status === 'live'"
          size="sm"
          variant="ghost"
          class="h-6 px-2 text-xs"
          title="全螢幕預覽"
          @click="openFullscreen"
        >
          <Maximize2 class="size-3" />
        </Button>
        <Button
          v-if="status === 'error' || status === 'chrome_offline'"
          size="sm"
          variant="outline"
          class="h-6 px-2 text-xs"
          @click="reconnect"
        >
          <RefreshCw class="mr-1 size-3" />
          重連
        </Button>
      </div>
    </div>

    <div
      v-if="status === 'live'"
      class="flex h-9 shrink-0 items-center gap-1 border-b bg-background px-2"
    >
      <Button
        size="icon"
        variant="ghost"
        class="size-7"
        title="上一頁"
        @click="goBack"
      >
        <ArrowLeft class="size-4" />
      </Button>
      <Button
        size="icon"
        variant="ghost"
        class="size-7"
        title="下一頁"
        @click="goForward"
      >
        <ArrowRight class="size-4" />
      </Button>
      <Button
        size="icon"
        variant="ghost"
        class="size-7"
        title="重新整理（Shift 強制重載）"
        @click="(e: MouseEvent) => reloadPage(e.shiftKey)"
      >
        <RefreshCw class="size-4" />
      </Button>
      <input
        v-model="urlInput"
        type="text"
        placeholder="輸入網址後按 Enter…"
        class="ml-1 h-7 flex-1 rounded-md border bg-background px-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring"
        @keydown.enter.prevent="submitUrl"
      />
    </div>

    <div
      class="relative flex flex-1 min-h-0 items-center justify-center overflow-hidden bg-black/90"
    >
      <template v-if="frameDataUrl && status === 'live'">
        <img
          ref="imgRef"
          :src="frameDataUrl"
          alt="browser screencast"
          class="max-h-full max-w-full select-none object-contain"
          draggable="false"
        />
        <textarea
          ref="overlayRef"
          spellcheck="false"
          autocomplete="off"
          autocorrect="off"
          autocapitalize="off"
          class="absolute inset-0 m-0 resize-none overflow-hidden border-0 p-0 outline-none"
          :class="interactive ? 'cursor-crosshair' : 'cursor-default'"
          style="background: transparent; color: transparent; caret-color: transparent;"
          @mousedown="onMouseDown"
          @mouseup="onMouseUp"
          @mousemove="onMouseMove"
          @wheel.prevent="onWheel"
          @contextmenu="onContextMenu"
          @keydown="onKeydown"
          @keyup="onKeyup"
          @compositionstart="onCompositionStart"
          @compositionend="onCompositionEnd"
          @input="onOverlayInput"
        />
      </template>
      <template v-else-if="status === 'connecting' || status === 'checking'">
        <div class="flex flex-col items-center gap-2 text-muted-foreground">
          <Loader2 class="size-6 animate-spin" />
          <span class="text-xs">{{ statusLabel }}</span>
        </div>
      </template>
      <template v-else-if="status === 'chrome_offline'">
        <div
          class="flex max-w-[80%] flex-col items-center gap-3 text-center text-muted-foreground"
        >
          <MonitorOff class="size-8" />
          <div>
            <p class="text-sm font-medium text-foreground">Chrome 未啟動</p>
            <p class="mt-1 text-xs">後端 Chrome 實例尚未啟動，無法串流畫面。</p>
          </div>
          <Button size="sm" variant="outline" @click="reconnect">
            <RefreshCw class="mr-1 size-3" />
            重新檢查
          </Button>
        </div>
      </template>
      <template v-else-if="status === 'error'">
        <div
          class="flex max-w-[80%] flex-col items-center gap-3 text-center text-muted-foreground"
        >
          <AlertTriangle class="size-8 text-destructive" />
          <div>
            <p class="text-sm font-medium text-foreground">連線失敗</p>
            <p class="mt-1 text-xs">
              {{ errorMessage ?? '無法連線到瀏覽器串流' }}
            </p>
          </div>
          <Button size="sm" variant="outline" @click="reconnect">
            <RefreshCw class="mr-1 size-3" />
            重新連線
          </Button>
        </div>
      </template>
      <template v-else>
        <div class="text-xs text-muted-foreground">尚未連線</div>
      </template>
    </div>

    <div
      v-if="fullscreenOpen"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-6"
      @click="fullscreenOpen = false"
    >
      <img
        v-if="frameDataUrl"
        :src="frameDataUrl"
        alt="browser screencast fullscreen"
        class="max-h-full max-w-full cursor-zoom-out object-contain"
      />
    </div>
  </div>
</template>

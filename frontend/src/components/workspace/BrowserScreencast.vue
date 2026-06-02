<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
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
  Plus,
  X,
  Monitor,
  Settings2,
  Check,
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  useBrowserScreencast,
  type ViewportSettings,
  type QualitySettings,
} from '@/composables/useBrowserScreencast'
import { useBrowserTabs } from '@/composables/useBrowserTabs'
import { virtualKeyCodeFor, textForKey } from '@/lib/browserKeymap'
import { useWorkspaceStore } from '@/stores/workspace'
import { storeToRefs } from 'pinia'
import PicobotIcon from '@/components/common/PicobotIcon.vue'

const workspace = useWorkspaceStore()
const { aiBrowserControlling, aiBrowserAction } = storeToRefs(workspace)

const {
  tabs: browserTabs,
  refresh: refreshTabs,
  open: openTabApi,
  close: closeTabApi,
} = useBrowserTabs()

const {
  status,
  frameDataUrl,
  errorMessage,
  fps,
  metadata,
  currentTargetId,
  switching,
  viewport,
  quality,
  connect,
  disconnect,
  sendInput,
  navigate,
  switchTarget,
  setViewport,
  resetViewport,
  setQuality,
} = useBrowserScreencast({
  onTabsChanged: async ({ currentClosed }) => {
    const list = await refreshTabs()
    // If the tab we were streaming got closed, jump to whichever tab is left.
    if (currentClosed) {
      const fallback = list[0]
      if (fallback) switchTarget(fallback.targetId)
    }
  },
})

const fullscreenOpen = ref(false)
const interactive = ref(true)

// While the agent is driving the page we lock out manual input so the user
// and the AI don't fight over the same cursor/keyboard.
const aiControlling = aiBrowserControlling
const effectiveInteractive = computed(
  () => interactive.value && !aiControlling.value,
)
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
      if (switching.value) return '切換分頁中…'
      if (aiControlling.value) return 'AI 操控中…'
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
      if (switching.value) return 'bg-amber-500'
      return aiControlling.value
        ? 'bg-indigo-500 animate-pulse'
        : 'bg-emerald-500 animate-pulse'
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
  void boot()
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
  if (!effectiveInteractive.value || status.value !== 'live') return
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
  if (!effectiveInteractive.value || status.value !== 'live') return
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
  if (!effectiveInteractive.value || status.value !== 'live') return
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
  if (!effectiveInteractive.value || status.value !== 'live') return
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
  if (effectiveInteractive.value) e.preventDefault()
}

function onKeydown(e: KeyboardEvent) {
  if (!effectiveInteractive.value || status.value !== 'live') return
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
  if (!effectiveInteractive.value || status.value !== 'live') return
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
  if (overlayRef.value) overlayRef.value.value = ''
}

function onOverlayInput(e: Event) {
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

function onTabClick(targetId: string) {
  if (targetId === currentTargetId.value) return
  switchTarget(targetId)
}

async function onNewTab() {
  const id = await openTabApi()
  if (id) switchTarget(id)
}

async function onCloseTab(targetId: string, e: MouseEvent) {
  e.stopPropagation()
  // Backend will emit tabs_changed; the onTabsChanged callback handles
  // fallback if the closed tab was the active one.
  await closeTabApi(targetId)
}

interface ViewportPreset {
  id: string
  label: string
  value: ViewportSettings | null
}

const VIEWPORT_PRESETS: ViewportPreset[] = [
  { id: 'default', label: '預設（瀏覽器原生）', value: null },
  { id: 'desktop', label: 'Desktop 1920×1080', value: { width: 1920, height: 1080 } },
  { id: 'laptop', label: 'Laptop 1366×768', value: { width: 1366, height: 768 } },
  { id: 'tablet', label: 'Tablet 768×1024', value: { width: 768, height: 1024 } },
  { id: 'mobile', label: 'Mobile 375×667', value: { width: 375, height: 667, deviceScaleFactor: 2, mobile: true } },
]

interface QualityPreset {
  id: string
  label: string
  value: QualitySettings
}

const QUALITY_PRESETS: QualityPreset[] = [
  { id: 'high', label: '高（1920×1080 · q85）', value: { maxWidth: 1920, maxHeight: 1080, quality: 85, everyNthFrame: 1 } },
  { id: 'medium', label: '中（1280×720 · q70）', value: { maxWidth: 1280, maxHeight: 720, quality: 70, everyNthFrame: 1 } },
  { id: 'low', label: '低（854×480 · q50）', value: { maxWidth: 854, maxHeight: 480, quality: 50, everyNthFrame: 1 } },
  { id: 'eco', label: '省頻寬（640×360 · q40 · 2fps）', value: { maxWidth: 640, maxHeight: 360, quality: 40, everyNthFrame: 15 } },
]

const viewportContainerRef = ref<HTMLDivElement | null>(null)

const viewportLabel = computed(() => {
  const v = viewport.value
  if (!v) return '預設'
  return `${v.width}×${v.height}`
})

const qualityLabel = computed(() => {
  const q = quality.value
  const match = QUALITY_PRESETS.find(
    (p) =>
      p.value.maxWidth === q.maxWidth &&
      p.value.maxHeight === q.maxHeight &&
      p.value.quality === q.quality &&
      p.value.everyNthFrame === q.everyNthFrame,
  )
  return match ? match.label.split('（')[0] : `${q.maxWidth}×${q.maxHeight}`
})

function applyViewportPreset(preset: ViewportPreset) {
  if (preset.value === null) resetViewport()
  else setViewport(preset.value)
}

function fitViewportToPanel() {
  const el = viewportContainerRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  if (rect.width < 64 || rect.height < 64) return
  setViewport({
    width: Math.round(rect.width),
    height: Math.round(rect.height),
    deviceScaleFactor: window.devicePixelRatio || 1,
  })
}

function applyQualityPreset(preset: QualityPreset) {
  setQuality(preset.value)
}

function isViewportActive(preset: ViewportPreset): boolean {
  if (preset.value === null) return viewport.value === null
  if (!viewport.value) return false
  return (
    viewport.value.width === preset.value.width &&
    viewport.value.height === preset.value.height &&
    (viewport.value.mobile ?? false) === (preset.value.mobile ?? false)
  )
}

function isQualityActive(preset: QualityPreset): boolean {
  const q = quality.value
  return (
    q.maxWidth === preset.value.maxWidth &&
    q.maxHeight === preset.value.maxHeight &&
    q.quality === preset.value.quality &&
    q.everyNthFrame === preset.value.everyNthFrame
  )
}

function tabLabel(tab: { title: string; url: string }): string {
  if (tab.title) return tab.title
  if (tab.url) {
    try {
      const u = new URL(tab.url)
      return u.hostname || tab.url
    } catch {
      return tab.url
    }
  }
  return '新分頁'
}

async function boot() {
  // Discover tabs first so we connect directly to whatever is open.
  const list = await refreshTabs()
  const target = list[0]?.targetId
  await connect(target)
}

// URL bar should mirror the active tab's URL when we know it.
watch(currentTargetId, (id) => {
  const tab = browserTabs.value.find((t) => t.targetId === id)
  if (tab) urlInput.value = tab.url
})

onMounted(() => {
  void boot()
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
        <DropdownMenu v-if="status === 'live'">
          <DropdownMenuTrigger as-child>
            <Button
              size="sm"
              variant="ghost"
              class="h-6 px-2 text-xs"
              title="切換頁面 viewport（影響網頁 layout）"
            >
              <Monitor class="mr-1 size-3" />
              {{ viewportLabel }}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" class="w-56">
            <DropdownMenuLabel class="text-[11px]">頁面 viewport</DropdownMenuLabel>
            <DropdownMenuItem
              v-for="preset in VIEWPORT_PRESETS"
              :key="preset.id"
              class="text-xs"
              @click="applyViewportPreset(preset)"
            >
              <Check
                class="mr-2 size-3"
                :class="isViewportActive(preset) ? 'opacity-100' : 'opacity-0'"
              />
              {{ preset.label }}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem class="text-xs" @click="fitViewportToPanel">
              <Maximize2 class="mr-2 size-3" />
              填滿目前面板
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <DropdownMenu v-if="status === 'live'">
          <DropdownMenuTrigger as-child>
            <Button
              size="sm"
              variant="ghost"
              class="h-6 px-2 text-xs"
              title="串流畫質（不影響網頁 layout）"
            >
              <Settings2 class="mr-1 size-3" />
              {{ qualityLabel }}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" class="w-64">
            <DropdownMenuLabel class="text-[11px]">串流畫質</DropdownMenuLabel>
            <DropdownMenuItem
              v-for="preset in QUALITY_PRESETS"
              :key="preset.id"
              class="text-xs"
              @click="applyQualityPreset(preset)"
            >
              <Check
                class="mr-2 size-3"
                :class="isQualityActive(preset) ? 'opacity-100' : 'opacity-0'"
              />
              {{ preset.label }}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Button
          v-if="status === 'live'"
          size="sm"
          variant="ghost"
          class="h-6 px-2 text-xs"
          :disabled="aiControlling"
          :title="
            aiControlling
              ? 'AI 操控中，已暫時鎖定手動輸入'
              : interactive
                ? '互動模式：開（點擊切換為僅檢視）'
                : '僅檢視（點擊切換為互動模式）'
          "
          @click="toggleInteractive"
        >
          <MousePointerClick v-if="interactive" class="mr-1 size-3 text-emerald-500" />
          <MousePointer v-else class="mr-1 size-3" />
          {{ aiControlling ? '已鎖定' : interactive ? '互動中' : '僅檢視' }}
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
      v-if="status === 'live' && browserTabs.length > 0"
      class="flex h-8 shrink-0 items-center gap-1 overflow-x-auto border-b bg-muted/20 px-2"
    >
      <button
        v-for="tab in browserTabs"
        :key="tab.targetId"
        type="button"
        :class="[
          'group flex h-6 min-w-0 max-w-[180px] shrink-0 items-center gap-1 rounded px-2 text-xs transition-colors',
          tab.targetId === currentTargetId
            ? 'bg-background ring-1 ring-border'
            : 'text-muted-foreground hover:bg-background/60',
        ]"
        :title="tab.url || tab.title"
        @click="onTabClick(tab.targetId)"
      >
        <span class="truncate">{{ tabLabel(tab) }}</span>
        <span
          v-if="browserTabs.length > 1"
          class="ml-0.5 grid size-4 shrink-0 place-items-center rounded text-muted-foreground opacity-0 hover:bg-muted hover:text-foreground group-hover:opacity-100"
          role="button"
          title="關閉分頁"
          @click="(e: MouseEvent) => onCloseTab(tab.targetId, e)"
        >
          <X class="size-3" />
        </span>
      </button>
      <button
        type="button"
        class="ml-1 grid size-6 shrink-0 place-items-center rounded text-muted-foreground hover:bg-background/60 hover:text-foreground"
        title="新增分頁"
        @click="onNewTab"
      >
        <Plus class="size-3.5" />
      </button>
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
      ref="viewportContainerRef"
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
          :class="
            aiControlling
              ? 'cursor-not-allowed'
              : interactive
                ? 'cursor-crosshair'
                : 'cursor-default'
          "
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
      <template v-else-if="status === 'live' && switching">
        <div class="flex flex-col items-center gap-2 text-muted-foreground">
          <Loader2 class="size-6 animate-spin" />
          <span class="text-xs">切換分頁中…</span>
        </div>
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

      <!-- AI control effect: pulsing glow border + scan line + status badge -->
      <template v-if="aiControlling && status === 'live'">
        <div class="ai-glow pointer-events-none absolute inset-0 z-20" aria-hidden="true" />
        <div
          class="pointer-events-none absolute left-3 top-3 z-30 flex items-center gap-1.5
                 rounded-full bg-indigo-600/90 py-1 pl-1 pr-2.5 text-[11px] font-medium
                 text-white shadow-lg backdrop-blur"
        >
          <PicobotIcon :size="18" state="running" glow class="relative -top-[2px]" />
          <span class="leading-none">AI 操控中{{ aiBrowserAction ? ` · ${aiBrowserAction}` : '' }}</span>
        </div>
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

<style scoped>
/* Pulsing inset glow — inset keeps it inside the overflow-hidden viewport so
   the border isn't clipped. The ::after layer sweeps a faint scan line. */
.ai-glow {
  box-shadow:
    inset 0 0 0 2px rgb(99 102 241 / 0.9),
    inset 0 0 26px rgb(99 102 241 / 0.45);
  animation: ai-glow-pulse 1.6s ease-in-out infinite;
}

.ai-glow::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(
    180deg,
    transparent,
    rgb(99 102 241 / 0.14),
    transparent
  );
  background-size: 100% 38%;
  background-repeat: no-repeat;
  animation: ai-scan 2.4s linear infinite;
}

@keyframes ai-glow-pulse {
  0%,
  100% {
    opacity: 0.5;
  }
  50% {
    opacity: 1;
  }
}

@keyframes ai-scan {
  from {
    background-position: 0 -40%;
  }
  to {
    background-position: 0 140%;
  }
}

@media (prefers-reduced-motion: reduce) {
  .ai-glow,
  .ai-glow::after {
    animation: none;
  }
  .ai-glow {
    opacity: 0.9;
  }
}
</style>

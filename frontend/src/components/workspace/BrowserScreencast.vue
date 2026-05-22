<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Loader2, RefreshCw, MonitorOff, AlertTriangle } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { useBrowserScreencast } from '@/composables/useBrowserScreencast'

const {
  status,
  frameDataUrl,
  errorMessage,
  fps,
  metadata,
  connect,
  disconnect,
} = useBrowserScreencast()

const fullscreenOpen = ref(false)

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
      <Button
        v-if="status === 'error' || status === 'chrome_offline'"
        size="sm"
        variant="outline"
        class="ml-auto h-6 px-2 text-xs"
        @click="reconnect"
      >
        <RefreshCw class="mr-1 size-3" />
        重連
      </Button>
    </div>

    <div
      class="relative flex flex-1 min-h-0 items-center justify-center overflow-hidden bg-black/90"
    >
      <template v-if="frameDataUrl && status === 'live'">
        <img
          :src="frameDataUrl"
          alt="browser screencast"
          class="max-h-full max-w-full cursor-zoom-in object-contain"
          @click="fullscreenOpen = true"
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

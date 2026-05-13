<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '@/lib/api'
import { WifiOff } from 'lucide-vue-next'

const offline = ref(false)
let timer: number | undefined

async function check() {
  try {
    await api.health()
    offline.value = false
  } catch {
    offline.value = true
  }
}

function schedule(delay: number) {
  if (timer !== undefined) window.clearTimeout(timer)
  timer = window.setTimeout(async () => {
    await check()
    schedule(offline.value ? 5_000 : 30_000)
  }, delay)
}

onMounted(() => {
  void check().then(() => schedule(offline.value ? 5_000 : 30_000))
})

onBeforeUnmount(() => {
  if (timer !== undefined) window.clearTimeout(timer)
})
</script>

<template>
  <Transition
    enter-active-class="transition duration-150"
    enter-from-class="-translate-y-full"
    leave-active-class="transition duration-150"
    leave-to-class="-translate-y-full"
  >
    <div
      v-if="offline"
      class="flex items-center justify-center gap-2 bg-destructive px-3 py-1.5 text-xs text-destructive-foreground"
    >
      <WifiOff class="size-3.5" />
      <span>已斷線，重新連線中…</span>
    </div>
  </Transition>
</template>

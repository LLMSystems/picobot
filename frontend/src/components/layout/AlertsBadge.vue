<script setup lang="ts">
// Compact alert-count badge for top bars. Mounting this badge ALWAYS starts
// the alerts store's polling/SSE lifecycle (even when no badge is visible),
// so the user still gets browser push notifications while in Chat mode and
// the badge reappears the moment an alert fires.
import { onBeforeUnmount, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { AlertTriangle } from 'lucide-vue-next'
import { useAlertsStore } from '@/stores/alerts'

const alerts = useAlertsStore()
const router = useRouter()

onMounted(() => alerts.startPolling())
onBeforeUnmount(() => alerts.stopPolling())

const dotClass = computed(() => {
  if (alerts.highestSeverity === 'critical') return 'bg-rose-500'
  if (alerts.highestSeverity === 'warning') return 'bg-amber-500'
  return 'bg-blue-500'
})

const pillClass = computed(() => {
  if (alerts.highestSeverity === 'critical')
    return 'border-rose-500/40 bg-rose-500/10 text-rose-700 dark:text-rose-300'
  if (alerts.highestSeverity === 'warning')
    return 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300'
  return 'border-blue-500/40 bg-blue-500/10 text-blue-700 dark:text-blue-300'
})

function open() {
  // Navigate to dashboard and let the hash trigger the AnchorRail scroll.
  router.push({ path: '/dashboard', hash: '#alerts' })
}
</script>

<template>
  <button
    v-if="alerts.activeCount > 0"
    type="button"
    class="inline-flex h-7 items-center gap-1.5 rounded-full border px-2 text-[11px] font-medium transition-colors hover:opacity-90"
    :class="pillClass"
    :title="`${alerts.activeCount} 個告警進行中`"
    @click="open"
  >
    <AlertTriangle class="size-3" />
    <span class="size-1.5 rounded-full" :class="dotClass" />
    <span>{{ alerts.activeCount }}</span>
  </button>
</template>

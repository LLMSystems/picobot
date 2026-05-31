<script setup lang="ts">
// Compact alert-count badge for top bars. Mounting this badge also drives
// the alerts store's polling/SSE lifecycle, so the user gets notified of new
// firings even while in Chat mode.
import { onBeforeUnmount, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { AlertTriangle, ShieldCheck } from 'lucide-vue-next'
import { useAlertsStore } from '@/stores/alerts'

const alerts = useAlertsStore()
const router = useRouter()

onMounted(() => alerts.startPolling())
onBeforeUnmount(() => alerts.stopPolling())

const dotClass = computed(() => {
  if (alerts.highestSeverity === 'critical') return 'bg-rose-500'
  if (alerts.highestSeverity === 'warning') return 'bg-amber-500'
  if (alerts.highestSeverity === 'info') return 'bg-blue-500'
  return 'bg-emerald-500'
})

const pillClass = computed(() => {
  if (alerts.highestSeverity === 'critical')
    return 'border-rose-500/40 bg-rose-500/10 text-rose-700 dark:text-rose-300'
  if (alerts.highestSeverity === 'warning')
    return 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300'
  if (alerts.highestSeverity === 'info')
    return 'border-blue-500/40 bg-blue-500/10 text-blue-700 dark:text-blue-300'
  return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
})

function open() {
  // Navigate to dashboard and let the hash trigger the AnchorRail scroll.
  router.push({ path: '/dashboard', hash: '#alerts' })
}
</script>

<template>
  <button
    type="button"
    class="inline-flex h-7 items-center gap-1.5 rounded-full border px-2 text-[11px] font-medium transition-colors hover:opacity-90"
    :class="pillClass"
    :title="alerts.activeCount > 0
      ? `${alerts.activeCount} 個告警進行中`
      : '沒有進行中的告警'"
    @click="open"
  >
    <template v-if="alerts.activeCount > 0">
      <AlertTriangle class="size-3" />
      <span class="size-1.5 rounded-full" :class="dotClass" />
      <span>{{ alerts.activeCount }}</span>
    </template>
    <template v-else>
      <ShieldCheck class="size-3" />
      <span>正常</span>
    </template>
  </button>
</template>

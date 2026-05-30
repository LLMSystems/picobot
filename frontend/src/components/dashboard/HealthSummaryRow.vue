<script setup lang="ts">
import { computed, type Component } from 'vue'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Activity,
  Chrome,
  Radio,
  CheckCircle2,
} from 'lucide-vue-next'
import type { MetricsCurrentSnapshot } from '@/lib/types'
import { accent, type AccentColor } from './colors'
import { formatPercent } from './format'

const props = defineProps<{
  snapshot: MetricsCurrentSnapshot | null
  loading?: boolean
}>()

interface HealthCard {
  label: string
  icon: Component
  value: string
  subtitle: string
  status: string
  color: AccentColor
}

// "Healthy" composite signal: CPU under 80%, 5xx rate under 1%, no degraded
// subsystems. Falls back to "unknown" until the first snapshot lands.
const overall = computed<HealthCard>(() => {
  const snap = props.snapshot
  if (!snap) {
    return {
      label: '系統狀態',
      icon: Activity,
      value: '尚未知道',
      subtitle: '尚未取得 snapshot',
      status: '...',
      color: 'slate',
    }
  }
  const cpu = snap.system.cpu_percent ?? 0
  const err5xx = snap.api.error_5xx_rate_1h ?? 0
  const err4xx = snap.api.error_4xx_rate_1h ?? 0
  const cpuHot = cpu >= 80
  const err5xxHot = err5xx >= 0.01
  const err4xxHot = err4xx >= 0.1
  if (cpuHot || err5xxHot) {
    return {
      label: '系統狀態',
      icon: Activity,
      value: '降級',
      subtitle: cpuHot ? `CPU ${cpu.toFixed(1)} %` : `5xx 比率 ${formatPercent(err5xx)}`,
      status: '降級',
      color: 'orange',
    }
  }
  if (err4xxHot) {
    return {
      label: '系統狀態',
      icon: Activity,
      value: '正常',
      subtitle: `輕微 4xx ${formatPercent(err4xx)}`,
      status: '正常',
      color: 'green',
    }
  }
  return {
    label: '系統狀態',
    icon: Activity,
    value: '正常',
    subtitle: '所有子系統運作正常',
    status: '正常',
    color: 'green',
  }
})

const chrome = computed<HealthCard>(() => {
  const alive = props.snapshot?.system.chrome_alive
  if (alive === null || alive === undefined) {
    return {
      label: '瀏覽器',
      icon: Chrome,
      value: '未啟用',
      subtitle: '未啟用瀏覽器整合',
      status: '未啟用',
      color: 'slate',
    }
  }
  return alive
    ? {
        label: '瀏覽器',
        icon: Chrome,
        value: '運作中',
        subtitle: '瀏覽器 process 運行中',
        status: '運作中',
        color: 'emerald',
      }
    : {
        label: '瀏覽器',
        icon: Chrome,
        value: '已停止',
        subtitle: '瀏覽器 process 未啟動',
        status: '已停止',
        color: 'rose',
      }
})

const liveConnections = computed<HealthCard>(() => {
  const conns = props.snapshot?.system.active_sse_connections ?? {}
  const total = Object.values(conns).reduce((a, b) => a + b, 0)
  const breakdown = Object.entries(conns)
    .filter(([, v]) => v > 0)
    .map(([k, v]) => `${k}: ${v}`)
    .join(' · ') || '目前無連線'
  return {
    label: '即時連線',
    icon: Radio,
    value: String(total),
    subtitle: breakdown,
    status: total > 0 ? '活躍' : '閒置',
    color: total > 0 ? 'blue' : 'slate',
  }
})

const toolSuccess = computed<HealthCard>(() => {
  const rate = props.snapshot?.agent.tool_success_rate ?? 1
  const total = props.snapshot?.agent.tool_calls_total ?? 0
  const ringColor: AccentColor =
    rate >= 0.95 ? 'green' : rate >= 0.8 ? 'amber' : 'rose'
  return {
    label: '工具成功率',
    icon: CheckCircle2,
    value: formatPercent(rate, 1),
    subtitle: `累積 ${total.toLocaleString()} 次呼叫`,
    status:
      rate >= 0.95 ? '正常'
      : rate >= 0.8 ? '注意'
      : '降級',
    color: ringColor,
  }
})

const cards = computed<HealthCard[]>(() => [
  overall.value,
  chrome.value,
  liveConnections.value,
  toolSuccess.value,
])
</script>

<template>
  <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
    <template v-if="loading">
      <Skeleton v-for="i in 4" :key="i" class="h-[88px] w-full" />
    </template>
    <template v-else>
      <Card
        v-for="card in cards"
        :key="card.label"
        class="border-border/60 shadow-none"
      >
        <CardContent class="flex items-center gap-3 px-4 py-3">
          <div
            class="flex size-10 shrink-0 items-center justify-center rounded-lg"
            :class="accent(card.color).iconBg"
          >
            <component
              :is="card.icon"
              class="size-5"
              :class="accent(card.color).iconText"
            />
          </div>
          <div class="flex min-w-0 flex-1 flex-col gap-0.5">
            <div class="flex items-center gap-2">
              <span class="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {{ card.label }}
              </span>
              <span
                class="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium leading-none"
                :class="[accent(card.color).pillBg, accent(card.color).pillText]"
              >
                <span
                  class="size-1.5 rounded-full"
                  :style="{ background: accent(card.color).hexLine }"
                />
                {{ card.status }}
              </span>
            </div>
            <div class="text-xl font-semibold leading-tight truncate">
              {{ card.value }}
            </div>
            <div class="text-[11px] text-muted-foreground truncate">
              {{ card.subtitle }}
            </div>
          </div>
        </CardContent>
      </Card>
    </template>
  </div>
</template>

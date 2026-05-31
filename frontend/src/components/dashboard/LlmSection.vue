<script setup lang="ts">
// Surfaces the `llm` block from /metrics/current + history series:
//   - StatCards row: call count, error rate, TTFT p95, iterations / chat
//   - TTFT vs Latency trend (two lines, range-controlled by parent picker)
//   - Per-model comparison table — directly from snap.llm.by_model_1h
//
// All three feeds rely on the LlmCallStore — LLM calls only show up once a
// chat has completed since the server picked up the new instrumentation, so
// expect a quiet section on a fresh restart.
import { computed } from 'vue'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Activity,
  AlertTriangle,
  Repeat,
  Sparkles,
  TimerReset,
  Zap,
} from 'lucide-vue-next'
import { accent } from './colors'
import { formatMs, formatNumber, formatPercent } from './format'
import { metricAccent } from './metricAccents'
import type { FiringWindow } from './LineChart.vue'
import type { MetricsCurrentSnapshot } from '@/lib/types'
import LineChart from './LineChart.vue'
import MetricsSection from './MetricsSection.vue'
import StatCard from './StatCard.vue'
import { useMetricsStore } from '@/stores/metrics'

const props = defineProps<{
  snapshot: MetricsCurrentSnapshot
  firingWindows?: {
    ttft?: FiringWindow[]
    latency?: FiringWindow[]
    error?: FiringWindow[]
  }
}>()

const metrics = useMetricsStore()
const llm = computed(() => props.snapshot.llm)

// TTFT + Latency series both come from category="llm" (the `latency_p95_ms`
// name also exists under category="api", so the category filter matters).
const trendSeries = computed(() => {
  const out = []
  const ttft = metrics.findSeries('ttft_p95_ms', null, 'llm')
  const latency = metrics.findSeries('latency_p95_ms', null, 'llm')
  if (ttft) out.push(ttft)
  if (latency) out.push(latency)
  return out
})

const trendFiringWindows = computed<FiringWindow[]>(() => [
  ...(props.firingWindows?.ttft ?? []),
  ...(props.firingWindows?.latency ?? []),
])

const errorRatePill = computed(() => {
  const rate = llm.value.error_rate_10m
  if (rate >= 0.05) return 'text-rose-600 dark:text-rose-400'
  if (rate > 0) return 'text-amber-600 dark:text-amber-400'
  return ''
})

const ttftPill = computed(() => {
  const v = llm.value.ttft_p95_ms
  if (v >= 1500) return 'text-rose-600 dark:text-rose-400'
  if (v >= 800) return 'text-amber-600 dark:text-amber-400'
  return ''
})
</script>

<template>
  <MetricsSection
    title="LLM 品質與可用性"
    subtitle="10 分鐘滾動視窗 — 呼叫成功率、首 Token 延遲、每 chat 迭代數"
  >
    <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
      <StatCard
        label="LLM 呼叫（10m）"
        :value="formatNumber(llm.calls_10m)"
        :hint="`${formatNumber(llm.chats_10m)} 個 chat`"
        :icon="Activity"
        :color="metricAccent('llm_calls')"
      />
      <StatCard
        label="錯誤率"
        :value="formatPercent(llm.error_rate_10m)"
        :hint="`${formatNumber(llm.errors_10m)} 錯誤 · ${formatNumber(llm.timeouts_10m)} timeout`"
        :icon="AlertTriangle"
        :color="metricAccent('llm_errors')"
        :class="errorRatePill"
      />
      <StatCard
        label="TTFT p95"
        :value="formatMs(llm.ttft_p95_ms)"
        :hint="`p50 ${formatMs(llm.ttft_p50_ms)}`"
        :icon="Zap"
        :color="metricAccent('llm_ttft')"
        :class="ttftPill"
      />
      <StatCard
        label="每 chat 迭代數"
        :value="llm.iterations_per_chat_avg.toFixed(1)"
        :hint="`max ${llm.iterations_per_chat_max} · p95 ${llm.iterations_per_chat_p95.toFixed(1)}`"
        :icon="Repeat"
        :color="metricAccent('llm_iterations')"
      />
    </div>

    <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card class="border-border/60 shadow-none">
        <CardHeader class="pb-2">
          <CardTitle class="flex items-center gap-2 text-sm">
            <TimerReset
              class="size-3.5"
              :style="{ color: accent(metricAccent('llm_ttft')).hexLine }"
            />
            TTFT vs 端到端延遲 p95
          </CardTitle>
        </CardHeader>
        <CardContent>
          <LineChart
            :series="trendSeries"
            :accent="metricAccent('llm_ttft')"
            :extra-accents="[metricAccent('llm_latency')]"
            :firing-windows="trendFiringWindows"
            :y-formatter="(v) => formatMs(v)"
          />
        </CardContent>
      </Card>

      <Card class="border-border/60 shadow-none">
        <CardHeader class="pb-2">
          <CardTitle class="flex items-center gap-2 text-sm">
            <Sparkles
              class="size-3.5"
              :style="{ color: accent(metricAccent('llm_calls')).hexLine }"
            />
            依模型比較（10m）
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div v-if="llm.by_model_10m.length === 0" class="py-6 text-center text-xs text-muted-foreground">
            尚無 LLM 呼叫資料
          </div>
          <div v-else class="overflow-x-auto">
            <table class="w-full text-xs">
              <thead class="text-muted-foreground">
                <tr class="border-b">
                  <th class="px-2 py-1.5 text-left font-medium">Model</th>
                  <th class="px-2 py-1.5 text-right font-medium">呼叫</th>
                  <th class="px-2 py-1.5 text-right font-medium">錯誤率</th>
                  <th class="px-2 py-1.5 text-right font-medium">TTFT p95</th>
                  <th class="px-2 py-1.5 text-right font-medium">Latency p95</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="m in llm.by_model_10m"
                  :key="m.model"
                  class="border-b border-border/40 last:border-b-0"
                >
                  <td class="px-2 py-1.5 font-mono">{{ m.model }}</td>
                  <td class="px-2 py-1.5 text-right">{{ formatNumber(m.calls) }}</td>
                  <td
                    class="px-2 py-1.5 text-right"
                    :class="m.error_rate > 0.05 ? 'text-rose-600 dark:text-rose-400' : ''"
                  >
                    {{ formatPercent(m.error_rate) }}
                  </td>
                  <td class="px-2 py-1.5 text-right">
                    {{ m.ttft_p95_ms > 0 ? formatMs(m.ttft_p95_ms) : '—' }}
                  </td>
                  <td class="px-2 py-1.5 text-right">{{ formatMs(m.latency_p95_ms) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  </MetricsSection>
</template>

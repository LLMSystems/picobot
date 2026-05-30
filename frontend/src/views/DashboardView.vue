<script setup lang="ts">
import BarChart from '@/components/dashboard/BarChart.vue'
import HealthSummaryRow from '@/components/dashboard/HealthSummaryRow.vue'
import LineChart from '@/components/dashboard/LineChart.vue'
import MetricsSection from '@/components/dashboard/MetricsSection.vue'
import RangePicker from '@/components/dashboard/RangePicker.vue'
import RecentActivityFeed from '@/components/dashboard/RecentActivityFeed.vue'
import SessionDetailPanel from '@/components/dashboard/SessionDetailPanel.vue'
import StatCard from '@/components/dashboard/StatCard.vue'
import { accent } from '@/components/dashboard/colors'
import {
    formatBytes,
    formatMs,
    formatNumber,
    formatPercent,
} from '@/components/dashboard/format'
import { metricAccent } from '@/components/dashboard/metricAccents'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import type { MetricsRange } from '@/lib/types'
import { useMetricsStore } from '@/stores/metrics'
import {
    Activity,
    ArrowDownToLine,
    ArrowUpFromLine,
    Bot,
    CheckCheck,
    Coins,
    Cpu,
    Database,
    Gauge,
    HardDrive,
    Layers,
    MemoryStick,
    PackageOpen,
    Radio,
    RefreshCw,
    Repeat,
    TimerReset,
    TriangleAlert,
    Users,
    Wrench
} from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted } from 'vue'

const metrics = useMetricsStore()

onMounted(() => metrics.startPolling())
onBeforeUnmount(() => metrics.stopPolling())

const snap = computed(() => metrics.current)
const loading = computed(() => metrics.loading && !metrics.isReady)
const lastUpdated = computed(() => {
  if (!metrics.lastFetchedAt) return ''
  return new Date(metrics.lastFetchedAt).toLocaleTimeString()
})

const sseTotal = computed(() => {
  const conns = snap.value?.system.active_sse_connections ?? {}
  return Object.values(conns).reduce((a, b) => a + b, 0)
})

const chromeLabel = computed(() => {
  const v = snap.value?.system.chrome_alive
  if (v === null || v === undefined) return '—'
  return v ? '運作中' : '已停止'
})

const sseBreakdown = computed(() => {
  const conns = snap.value?.system.active_sse_connections ?? {}
  const entries = Object.entries(conns)
  if (entries.length === 0) return undefined
  return entries.map(([k, v]) => `${k}: ${v}`).join(' · ')
})

const dbRowSummary = computed(() => {
  const rows = snap.value?.system.db_row_counts ?? {}
  return Object.entries(rows)
    .map(([k, v]) => `${k}: ${formatNumber(v)}`)
    .join(' · ') || undefined
})

function onRangeChange(value: MetricsRange) {
  void metrics.refreshHistory(value)
}

const cpuSeries = computed(() => {
  const s = metrics.findSeries('cpu_percent', null, 'system')
  return s ? [s] : []
})
const rssSeries = computed(() => {
  const s = metrics.findSeries('rss_bytes', null, 'system')
  return s ? [s] : []
})
const tokenSeries = computed(() => {
  const result = []
  const tIn = metrics.findSeries('tokens_in_24h', null, 'usage')
  const tOut = metrics.findSeries('tokens_out_24h', null, 'usage')
  if (tIn) result.push(tIn)
  if (tOut) result.push(tOut)
  return result
})
const toolCallsSeries = computed(() => {
  const s = metrics.findSeries('tool_calls_total', null, 'agent')
  return s ? [s] : []
})
const qpsSeries = computed(() => {
  const s = metrics.findSeries('qps_1m', null, 'api')
  return s ? [s] : []
})
const latencySeries = computed(() => {
  const s = metrics.findSeries('latency_p95_ms', null, 'api')
  return s ? [s] : []
})
const errorSeries = computed(() => {
  const result = []
  const e4 = metrics.findSeries('error_4xx_rate_1h', null, 'api')
  const e5 = metrics.findSeries('error_5xx_rate_1h', null, 'api')
  if (e4) result.push(e4)
  if (e5) result.push(e5)
  return result
})
const subagentRunsSeries = computed(() => {
  const s = metrics.findSeries('runs_24h', null, 'subagents')
  return s ? [s] : []
})
const subagentDurationSeries = computed(() => {
  const s = metrics.findSeries('duration_p95_ms', null, 'subagents')
  return s ? [s] : []
})

// Bar items derived from snap.agent.top_tools, hint includes success rate.
const topToolBars = computed(() => {
  const tools = snap.value?.agent.top_tools ?? []
  return tools.map((t) => ({
    label: t.name,
    value: t.count,
    hint: `成功率 ${formatPercent(t.success_rate)}`,
  }))
})

const topEndpointBars = computed(() => {
  const endpoints = snap.value?.api.top_endpoints_1h ?? []
  return endpoints.map((e) => ({
    label: e.endpoint,
    value: e.count,
    hint: `p95 ${formatMs(e.latency_p95_ms)}`,
  }))
})

// Stacked bars per model — primary = tokens in, secondary = tokens out.
const tokenByModelBars = computed(() => {
  const list = snap.value?.usage.by_model_24h ?? []
  return list.map((m) => ({
    label: m.model,
    value: m.tokens_in,
    secondary: m.tokens_out,
    hint: `合計 ${formatNumber(m.tokens_in + m.tokens_out)} tokens`,
  }))
})
</script>

<template>
  <div class="flex flex-col">
    <div
      class="sticky top-0 z-20 flex items-center justify-between gap-3 border-b bg-background/95 px-6 py-2 backdrop-blur"
    >
      <div class="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span class="text-sm font-semibold text-foreground">Dashboard</span>
        <span
          class="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium"
          :class="metrics.liveConnected
            ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
            : 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300'"
        >
          <span
            class="size-1.5 rounded-full"
            :class="metrics.liveConnected ? 'bg-emerald-500' : 'bg-amber-500'"
          />
          {{ metrics.liveConnected ? 'Live' : '輪詢中' }}
        </span>
        <span v-if="lastUpdated">最後更新 {{ lastUpdated }}</span>
      </div>
      <div class="flex items-center gap-2">
        <RangePicker :model-value="metrics.historyRange" @update:model-value="onRangeChange" />
        <Button
          variant="outline"
          size="sm"
          :disabled="metrics.loading"
          @click="() => { metrics.refreshCurrent(); metrics.refreshHistory(metrics.historyRange) }"
        >
          <RefreshCw class="size-3.5" :class="{ 'animate-spin': metrics.loading }" />
          重新整理
        </Button>
      </div>
    </div>

    <div class="px-6 py-4 space-y-6">
      <template v-if="loading">
        <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Skeleton v-for="i in 8" :key="i" class="h-[120px] w-full" />
        </div>
      </template>

      <template v-else-if="metrics.lastError">
        <Card class="border-destructive/50">
          <CardContent class="px-4 py-3 text-sm text-destructive">
            載入 metrics 失敗：{{ metrics.lastError.message }}
          </CardContent>
        </Card>
      </template>

      <template v-else-if="snap">
        <section data-anchor="health" class="scroll-mt-20">
          <MetricsSection title="系統健康總覽">
            <HealthSummaryRow :snapshot="snap" :loading="false" />
          </MetricsSection>
        </section>

        <section data-anchor="resources" class="scroll-mt-20 grid grid-cols-1 gap-6 xl:grid-cols-2">
          <MetricsSection title="系統資源">
            <div class="grid grid-cols-2 gap-2 sm:grid-cols-3">
              <StatCard
                label="CPU"
                :value="snap.system.cpu_percent === null ? '—' : `${snap.system.cpu_percent.toFixed(1)} %`"
                :icon="Cpu"
                :color="metricAccent('cpu')"
              />
              <StatCard
                label="記憶體 (RSS)"
                :value="formatBytes(snap.system.rss_bytes)"
                :icon="MemoryStick"
                :color="metricAccent('memory')"
              />
              <StatCard
                label="執行緒"
                :value="formatNumber(snap.system.threads)"
                :icon="Layers"
                :color="metricAccent('threads')"
              />
              <StatCard
                label="資料庫"
                :value="formatBytes(snap.system.db_file_bytes)"
                :icon="Database"
                :color="metricAccent('db')"
              />
              <StatCard
                label="Workspace"
                :value="formatBytes(snap.system.workspace_total_bytes)"
                :icon="HardDrive"
                :color="metricAccent('workspace')"
              />
              <StatCard
                label="活躍 SSE"
                :value="formatNumber(sseTotal)"
                :icon="Radio"
                :color="metricAccent('sse')"
              />
            </div>
          </MetricsSection>

          <MetricsSection title="Agent 活動">
            <div class="grid grid-cols-2 gap-2 sm:grid-cols-3">
              <StatCard
                label="迭代次數"
                :value="formatNumber(snap.agent.iterations_total)"
                hint="累積 assistant 輪數"
                :icon="Repeat"
                :color="metricAccent('iterations')"
              />
              <StatCard
                label="工具呼叫"
                :value="formatNumber(snap.agent.tool_calls_total)"
                :icon="Wrench"
                :color="metricAccent('tool_calls')"
              />
              <StatCard
                label="工具成功率"
                :value="formatPercent(snap.agent.tool_success_rate)"
                :icon="CheckCheck"
                :color="metricAccent('tool_success')"
              />
              <StatCard
                label="子代理執行次數"
                :value="formatNumber(snap.subagents.runs_24h)"
                :hint="`執行中 ${formatNumber(snap.subagents.running_now)}`"
                :icon="Bot"
                :color="metricAccent('subagent_runs')"
              />
              <StatCard
                label="子代理成功率"
                :value="formatPercent(snap.subagents.success_rate_24h)"
                :hint="`p95 ${formatMs(snap.subagents.duration_p95_ms)}`"
                :icon="CheckCheck"
                :color="metricAccent('subagent_success')"
              />
              <StatCard
                label="活躍 Sessions"
                :value="formatNumber(snap.agent.sessions_active_24h)"
                :hint="`新建 ${formatNumber(snap.agent.sessions_new_24h)} · 累積 ${formatNumber(snap.agent.sessions_total)}`"
                :icon="Users"
                :color="metricAccent('sessions')"
              />
            </div>
          </MetricsSection>
        </section>

        <section data-anchor="trends" class="scroll-mt-20">
        <MetricsSection
          title="趨勢"
          :subtitle="`歷史 ${metrics.historyRange} · bucket ${metrics.history?.bucket ?? '—'}`"
        >
          <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Card class="border-border/60 shadow-none">
              <CardHeader class="pb-2">
                <CardTitle class="flex items-center gap-2 text-sm">
                  <Cpu class="size-3.5" :style="{ color: accent(metricAccent('cpu')).hexLine }" />
                  CPU 使用率
                </CardTitle>
              </CardHeader>
              <CardContent>
                <LineChart
                  :series="cpuSeries"
                  :accent="metricAccent('cpu')"
                  :y-formatter="(v) => `${v.toFixed(1)}%`"
                />
              </CardContent>
            </Card>
            <Card class="border-border/60 shadow-none">
              <CardHeader class="pb-2">
                <CardTitle class="flex items-center gap-2 text-sm">
                  <MemoryStick class="size-3.5" :style="{ color: accent(metricAccent('memory')).hexLine }" />
                  記憶體 (RSS)
                </CardTitle>
              </CardHeader>
              <CardContent>
                <LineChart
                  :series="rssSeries"
                  :accent="metricAccent('memory')"
                  :y-formatter="(v) => formatBytes(v)"
                />
              </CardContent>
            </Card>
            <Card class="border-border/60 shadow-none">
              <CardHeader class="pb-2">
                <CardTitle class="flex items-center gap-2 text-sm">
                  <Coins class="size-3.5" :style="{ color: accent(metricAccent('tokens_in')).hexLine }" />
                  Tokens（輸入 / 輸出，24h 滾動）
                </CardTitle>
              </CardHeader>
              <CardContent>
                <LineChart
                  :series="tokenSeries"
                  :accent="metricAccent('tokens_in')"
                  :extra-accents="[metricAccent('tokens_out')]"
                />
              </CardContent>
            </Card>
            <Card class="border-border/60 shadow-none">
              <CardHeader class="pb-2">
                <CardTitle class="flex items-center gap-2 text-sm">
                  <Wrench class="size-3.5" :style="{ color: accent(metricAccent('tool_calls')).hexLine }" />
                  工具呼叫（累積）
                </CardTitle>
              </CardHeader>
              <CardContent>
                <LineChart :series="toolCallsSeries" :accent="metricAccent('tool_calls')" />
              </CardContent>
            </Card>
          </div>
        </MetricsSection>
        </section>

        <section data-anchor="api-trends" class="scroll-mt-20">
        <MetricsSection
          title="API 與子代理趨勢"
          subtitle="次要指標 — 同樣套用 RangePicker"
        >
          <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Card class="border-border/60 shadow-none">
              <CardHeader class="pb-2">
                <CardTitle class="flex items-center gap-2 text-sm">
                  <Gauge class="size-3.5" :style="{ color: accent(metricAccent('qps')).hexLine }" />
                  QPS (1m)
                </CardTitle>
              </CardHeader>
              <CardContent>
                <LineChart
                  :series="qpsSeries"
                  :accent="metricAccent('qps')"
                  :height="180"
                  :y-formatter="(v) => v.toFixed(2)"
                />
              </CardContent>
            </Card>
            <Card class="border-border/60 shadow-none">
              <CardHeader class="pb-2">
                <CardTitle class="flex items-center gap-2 text-sm">
                  <TimerReset class="size-3.5" :style="{ color: accent(metricAccent('latency')).hexLine }" />
                  API 延遲 p95
                </CardTitle>
              </CardHeader>
              <CardContent>
                <LineChart
                  :series="latencySeries"
                  :accent="metricAccent('latency')"
                  :height="180"
                  :y-formatter="(v) => formatMs(v)"
                />
              </CardContent>
            </Card>
            <Card class="border-border/60 shadow-none">
              <CardHeader class="pb-2">
                <CardTitle class="flex items-center gap-2 text-sm">
                  <TriangleAlert class="size-3.5" :style="{ color: accent(metricAccent('errors')).hexLine }" />
                  4xx / 5xx 比率（1h）
                </CardTitle>
              </CardHeader>
              <CardContent>
                <LineChart
                  :series="errorSeries"
                  :accent="metricAccent('warn')"
                  :extra-accents="[metricAccent('errors')]"
                  :height="180"
                  as-percent
                />
              </CardContent>
            </Card>
            <Card class="border-border/60 shadow-none">
              <CardHeader class="pb-2">
                <CardTitle class="flex items-center gap-2 text-sm">
                  <Activity class="size-3.5" :style="{ color: accent(metricAccent('subagent_running')).hexLine }" />
                  子代理執行次數 / 耗時 p95
                </CardTitle>
              </CardHeader>
              <CardContent>
                <LineChart
                  :series="[...subagentRunsSeries, ...subagentDurationSeries]"
                  :accent="metricAccent('subagent_running')"
                  :extra-accents="[metricAccent('subagent_p95')]"
                  :height="180"
                />
              </CardContent>
            </Card>
          </div>
        </MetricsSection>
        </section>

        <section data-anchor="lists" class="scroll-mt-20 grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
          <Card class="border-border/60 shadow-none">
            <CardHeader class="pb-2">
              <CardTitle class="flex items-center gap-2 text-sm">
                <Wrench class="size-3.5" :style="{ color: accent(metricAccent('tool_calls')).hexLine }" />
                熱門工具
              </CardTitle>
            </CardHeader>
            <CardContent>
              <BarChart
                :items="topToolBars"
                :accent="metricAccent('tool_calls')"
                show-percent
              />
            </CardContent>
          </Card>
          <Card class="border-border/60 shadow-none">
            <CardHeader class="pb-2">
              <CardTitle class="flex items-center gap-2 text-sm">
                <Gauge class="size-3.5" :style="{ color: accent(metricAccent('endpoints')).hexLine }" />
                熱門 endpoints（1h）
              </CardTitle>
            </CardHeader>
            <CardContent>
              <BarChart
                :items="topEndpointBars"
                :accent="metricAccent('endpoints')"
                show-percent
              />
            </CardContent>
          </Card>
          <RecentActivityFeed :limit="6" />
        </section>

        <section data-anchor="usage" class="scroll-mt-20">
        <MetricsSection
          title="Token 用量（24h）"
          subtitle="僅統計目前 process 期間累積的 chat tokens（Phase 1 限制）"
        >
          <div class="grid grid-cols-2 gap-3 md:grid-cols-3">
            <StatCard
              label="輸入 Tokens"
              :value="formatNumber(snap.usage.tokens_in_24h)"
              :icon="ArrowDownToLine"
              color="purple"
            />
            <StatCard
              label="輸出 Tokens"
              :value="formatNumber(snap.usage.tokens_out_24h)"
              :icon="ArrowUpFromLine"
              color="pink"
            />
            <StatCard
              label="使用模型數"
              :value="formatNumber(snap.usage.by_model_24h.length)"
              :icon="PackageOpen"
              color="cyan"
            />
          </div>
          <Card v-if="snap.usage.by_model_24h.length" class="border-border/60 shadow-none">
            <CardHeader class="pb-2">
              <CardTitle class="flex items-center gap-2 text-sm">
                <PackageOpen
                  class="size-3.5"
                  :style="{ color: accent(metricAccent('models')).hexLine }"
                />
                依模型分佈（輸入 / 輸出 tokens）
              </CardTitle>
            </CardHeader>
            <CardContent>
              <BarChart
                :items="tokenByModelBars"
                :accent="metricAccent('tokens_in')"
                :secondary-accent="metricAccent('tokens_out')"
                primary-label="輸入"
                secondary-label="輸出"
                show-value
              />
            </CardContent>
          </Card>
        </MetricsSection>
        </section>

        <section data-anchor="session" class="scroll-mt-20">
          <SessionDetailPanel />
        </section>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  AlertTriangle,
  ArrowRight,
  BellOff,
  BellRing,
  CheckCircle2,
  ChevronDown,
  Clock,
  History,
  PlayCircle,
  ShieldCheck,
  Target,
  Timer,
  X,
} from 'lucide-vue-next'
import { useAlertsStore } from '@/stores/alerts'
import { useNotifications } from '@/composables/useNotifications'
import { relativeTime } from '@/lib/format'
import { toast } from 'vue-sonner'
import type { AlertEvent, AlertSeverity } from '@/lib/types'

const alerts = useAlertsStore()
const notifs = useNotifications()
const showHistory = ref(false)
const historyLoaded = ref(false)

// History filters — frontend-only, applied to the already-loaded list.
const filterSeverity = ref<'all' | AlertSeverity>('all')
const filterRule = ref<'all' | string>('all')

// Currently-expanded history row id (single-open accordion).
const expandedHistoryId = ref<number | null>(null)

function toggleExpand(id: number) {
  expandedHistoryId.value = expandedHistoryId.value === id ? null : id
}

function formatDateTime(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

function formatDuration(fromIso: string, toIso: string | null): string {
  if (!fromIso) return '—'
  const from = new Date(fromIso).getTime()
  const to = toIso ? new Date(toIso).getTime() : Date.now()
  if (Number.isNaN(from) || Number.isNaN(to)) return '—'
  const total = Math.max(0, Math.floor((to - from) / 1000))
  if (total < 60) return `${total} 秒`
  const min = Math.floor(total / 60)
  const sec = total % 60
  if (min < 60) return sec > 0 ? `${min} 分 ${sec} 秒` : `${min} 分鐘`
  const hr = Math.floor(min / 60)
  const restMin = min % 60
  if (hr < 24) return restMin > 0 ? `${hr} 小時 ${restMin} 分` : `${hr} 小時`
  const day = Math.floor(hr / 24)
  const restHr = hr % 24
  return restHr > 0 ? `${day} 天 ${restHr} 小時` : `${day} 天`
}

function formatContext(ctx: Record<string, unknown>): string {
  if (!ctx || Object.keys(ctx).length === 0) return '—'
  return Object.entries(ctx)
    .map(([k, v]) => `${k}: ${JSON.stringify(v)}`)
    .join(' · ')
}

// metric_path → DashboardView anchor section id. Used by the "view trend"
// button to scroll the user to the relevant LineChart (which already shows
// firing periods via markArea).
const METRIC_ANCHOR_MAP: Record<string, string> = {
  'system.cpu_percent': 'trends',
  'system.rss_bytes': 'trends',
  'system.db_file_bytes': 'trends',
  'agent.tool_calls_total': 'trends',
  'agent.tool_success_rate': 'trends',
  'usage.tokens_in_24h': 'trends',
  'usage.tokens_out_24h': 'trends',
  'api.qps_1m': 'api-trends',
  'api.latency_p95_ms': 'api-trends',
  'api.error_4xx_rate_1h': 'api-trends',
  'api.error_5xx_rate_1h': 'api-trends',
  'subagents.runs_24h': 'api-trends',
  'subagents.duration_p95_ms': 'api-trends',
  'subagents.longest_running_seconds': 'api-trends',
  'system.chrome_alive': 'health',
}

function jumpToTrend(metricPath: string) {
  const anchorId = METRIC_ANCHOR_MAP[metricPath] ?? 'trends'
  const el = document.querySelector(`[data-anchor="${anchorId}"]`) as HTMLElement | null
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

onMounted(() => alerts.startPolling())
onBeforeUnmount(() => alerts.stopPolling())

async function toggleHistory() {
  showHistory.value = !showHistory.value
  if (showHistory.value && !historyLoaded.value) {
    await alerts.refreshHistory(100)
    historyLoaded.value = true
  }
}

const SEVERITY_STYLES: Record<
  AlertSeverity,
  { pill: string; dot: string; icon: string; iconBg: string; border: string }
> = {
  critical: {
    pill: 'bg-rose-500/15 text-rose-700 dark:text-rose-300',
    dot: 'bg-rose-500',
    icon: 'text-rose-600 dark:text-rose-400',
    iconBg: 'bg-rose-500/15 dark:bg-rose-500/20',
    border: 'border-rose-500/40',
  },
  warning: {
    pill: 'bg-amber-500/15 text-amber-700 dark:text-amber-300',
    dot: 'bg-amber-500',
    icon: 'text-amber-600 dark:text-amber-400',
    iconBg: 'bg-amber-500/15 dark:bg-amber-500/20',
    border: 'border-amber-500/40',
  },
  info: {
    pill: 'bg-blue-500/15 text-blue-700 dark:text-blue-300',
    dot: 'bg-blue-500',
    icon: 'text-blue-600 dark:text-blue-400',
    iconBg: 'bg-blue-500/15 dark:bg-blue-500/20',
    border: 'border-blue-500/40',
  },
}

function styleFor(severity: AlertSeverity) {
  return SEVERITY_STYLES[severity] ?? SEVERITY_STYLES.info
}

function severityLabel(severity: AlertSeverity): string {
  if (severity === 'critical') return '嚴重'
  if (severity === 'warning') return '警告'
  return '提示'
}

function ruleLabel(ev: { rule_name: string; display_name: string | null }): string {
  return ev.display_name || ev.rule_name
}

function silencedUntilLabel(ruleName: string): string | null {
  const iso = alerts.silences[ruleName]
  if (!iso) return null
  return relativeTime(iso) || iso
}

const orderedActive = computed(() => {
  const order: AlertSeverity[] = ['critical', 'warning', 'info']
  return [...alerts.active].sort((a, b) => {
    const sa = order.indexOf(a.severity)
    const sb = order.indexOf(b.severity)
    if (sa !== sb) return sa - sb
    return b.fired_at.localeCompare(a.fired_at)
  })
})

const filteredHistory = computed(() => {
  let list = [...alerts.history]
  if (filterSeverity.value !== 'all') {
    list = list.filter((e) => e.severity === filterSeverity.value)
  }
  if (filterRule.value !== 'all') {
    list = list.filter((e) => e.rule_name === filterRule.value)
  }
  list.sort((a, b) => b.fired_at.localeCompare(a.fired_at))
  return list
})

const historyRuleOptions = computed(() => {
  // Pair (rule_name → display_name) so the dropdown can show the Chinese
  // label while filtering by the canonical name.
  const byName = new Map<string, string>()
  for (const e of alerts.history) {
    if (!byName.has(e.rule_name)) {
      byName.set(e.rule_name, e.display_name || e.rule_name)
    }
  }
  return Array.from(byName, ([name, label]) => ({ name, label })).sort(
    (a, b) => a.label.localeCompare(b.label),
  )
})

// Silence duration options exposed via dropdown next to each alert.
const SILENCE_DURATIONS: { label: string; seconds: number }[] = [
  { label: '靜音 1 小時', seconds: 60 * 60 },
  { label: '靜音 6 小時', seconds: 6 * 60 * 60 },
  { label: '靜音 24 小時', seconds: 24 * 60 * 60 },
  { label: '靜音 7 天', seconds: 7 * 24 * 60 * 60 },
]

async function ack(event: AlertEvent) {
  await alerts.acknowledge(event.id)
}

async function silence(event: AlertEvent, durationSeconds: number) {
  await alerts.silenceRule(event.rule_name, durationSeconds)
}

async function unsilence(ruleName: string) {
  await alerts.unsilenceRule(ruleName)
}

function durationLabel(eventOrIso: AlertEvent | string): string {
  const iso = typeof eventOrIso === 'string' ? eventOrIso : eventOrIso.fired_at
  return relativeTime(iso) || ''
}

// Pure client-side notification — used to verify browser permissions and
// styling without having to actually trigger a real alert condition.
async function sendTestNotification() {
  if (!notifs.supported) {
    toast.error('此瀏覽器不支援通知')
    return
  }
  if (notifs.permission.value !== 'granted') {
    const ok = await notifs.enable()
    if (!ok) {
      toast.error('通知權限未授予', {
        description: '請在瀏覽器設定開啟此網站的通知權限',
      })
      return
    }
  }
  notifs.notifyAlert({
    title: '【測試】picobot 告警',
    body: '這是一則測試通知 — 真的告警也會長這樣',
    tag: `picobot-alert-test-${Date.now()}`,
  })
  toast.success('已發送測試通知', {
    description: '若看不到，請檢查瀏覽器通知權限與 OS 設定',
  })
}
</script>

<template>
  <Card class="border-border/60 shadow-none">
    <CardHeader class="pb-3">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <CardTitle class="flex items-center gap-2 text-base">
          <AlertTriangle
            class="size-4"
            :class="alerts.highestSeverity ? styleFor(alerts.highestSeverity).icon : 'text-muted-foreground'"
          />
          告警
          <span
            v-if="alerts.activeCount > 0"
            class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium"
            :class="alerts.highestSeverity
              ? [styleFor(alerts.highestSeverity).pill]
              : []"
          >
            <span
              class="size-1.5 rounded-full"
              :class="alerts.highestSeverity
                ? styleFor(alerts.highestSeverity).dot
                : ''"
            />
            {{ alerts.activeCount }} 進行中
          </span>
          <span
            v-else
            class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
          >
            <ShieldCheck class="size-3" />
            一切正常
          </span>
          <span
            class="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium"
            :class="alerts.liveConnected
              ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
              : 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300'"
            :title="alerts.liveConnected
              ? 'SSE 串流連線中'
              : 'SSE 未連線，使用輪詢 fallback'"
          >
            <span
              class="size-1.5 rounded-full"
              :class="alerts.liveConnected ? 'bg-emerald-500' : 'bg-amber-500'"
            />
            {{ alerts.liveConnected ? 'Live' : '輪詢中' }}
          </span>
        </CardTitle>
        <div class="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            class="h-7 gap-1.5"
            title="發送一則測試 browser 通知"
            @click="sendTestNotification"
          >
            <PlayCircle class="size-3.5" />
            測試通知
          </Button>
          <Button variant="ghost" size="sm" class="h-7 gap-1.5" @click="toggleHistory">
            <History class="size-3.5" />
            {{ showHistory ? '隱藏歷史' : '查看歷史' }}
          </Button>
        </div>
      </div>
    </CardHeader>
    <CardContent class="space-y-3">
      <template v-if="alerts.loading && alerts.active.length === 0">
        <Skeleton class="h-16 w-full" />
        <Skeleton class="h-16 w-full" />
      </template>

      <template v-else-if="orderedActive.length === 0">
        <div class="rounded-md border border-dashed px-4 py-6 text-center">
          <ShieldCheck class="mx-auto size-6 text-emerald-500" />
          <p class="mt-2 text-sm font-medium">沒有進行中的 alert</p>
          <p class="text-xs text-muted-foreground">所有規則目前都未觸發</p>
        </div>
      </template>

      <template v-else>
        <div
          v-for="ev in orderedActive"
          :key="ev.id"
          class="flex flex-col gap-2 rounded-md border bg-card px-4 py-3"
          :class="styleFor(ev.severity).border"
        >
          <div class="flex flex-wrap items-start justify-between gap-2">
            <div class="flex items-start gap-3">
              <div
                class="flex size-9 shrink-0 items-center justify-center rounded-lg"
                :class="styleFor(ev.severity).iconBg"
              >
                <AlertTriangle
                  class="size-4"
                  :class="styleFor(ev.severity).icon"
                />
              </div>
              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-2">
                  <span
                    class="rounded-full px-2 py-0.5 text-[10px] font-semibold leading-none"
                    :class="styleFor(ev.severity).pill"
                  >
                    {{ severityLabel(ev.severity) }}
                  </span>
                  <span class="text-sm font-medium">{{ ruleLabel(ev) }}</span>
                  <span
                    v-if="ev.acknowledged_at"
                    class="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground"
                  >
                    <CheckCircle2 class="size-3" />
                    已確認
                  </span>
                  <span
                    v-if="alerts.silences[ev.rule_name]"
                    class="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground"
                  >
                    <BellOff class="size-3" />
                    靜音 {{ silencedUntilLabel(ev.rule_name) }}
                  </span>
                </div>
                <p class="mt-1 text-xs text-muted-foreground">{{ ev.description }}</p>
                <p class="mt-1 font-mono text-[11px] text-muted-foreground">
                  {{ ev.metric_path }} {{ ev.comparator }} {{ ev.threshold }}
                  <span v-if="ev.trigger_value !== null" class="text-foreground">
                    · 當前值 {{ ev.trigger_value }}
                  </span>
                </p>
                <p class="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
                  <Clock class="size-3" />
                  起始 {{ durationLabel(ev) }}
                </p>
              </div>
            </div>
            <div class="flex shrink-0 flex-wrap items-center gap-1">
              <Button
                v-if="!ev.acknowledged_at"
                variant="outline"
                size="sm"
                class="h-7 text-xs"
                @click="ack(ev)"
              >
                確認
              </Button>
              <DropdownMenu v-if="!alerts.silences[ev.rule_name]">
                <DropdownMenuTrigger as-child>
                  <Button variant="outline" size="sm" class="h-7 text-xs">
                    <BellOff class="size-3" />
                    靜音
                    <ChevronDown class="size-3" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" class="w-40">
                  <DropdownMenuItem
                    v-for="opt in SILENCE_DURATIONS"
                    :key="opt.seconds"
                    @click="silence(ev, opt.seconds)"
                  >
                    <span class="text-sm">{{ opt.label }}</span>
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <Button
                v-else
                variant="outline"
                size="sm"
                class="h-7 text-xs"
                @click="unsilence(ev.rule_name)"
              >
                <BellRing class="size-3" />
                取消靜音
              </Button>
            </div>
          </div>
        </div>
      </template>

      <div v-if="showHistory" class="mt-2 border-t pt-3">
        <div class="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <div class="flex items-center gap-2">
            <span>歷史 alerts</span>
            <span class="text-[10px]">（{{ filteredHistory.length }} 筆）</span>
          </div>
          <div class="flex items-center gap-2">
            <Select v-model="filterSeverity">
              <SelectTrigger class="h-7 w-[120px] text-xs">
                <SelectValue placeholder="嚴重度" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部嚴重度</SelectItem>
                <SelectItem value="critical">嚴重</SelectItem>
                <SelectItem value="warning">警告</SelectItem>
                <SelectItem value="info">提示</SelectItem>
              </SelectContent>
            </Select>
            <Select v-model="filterRule">
              <SelectTrigger class="h-7 w-[160px] text-xs">
                <SelectValue placeholder="規則" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部規則</SelectItem>
                <SelectItem
                  v-for="opt in historyRuleOptions"
                  :key="opt.name"
                  :value="opt.name"
                >
                  {{ opt.label }}
                </SelectItem>
              </SelectContent>
            </Select>
            <Button
              variant="ghost"
              size="sm"
              class="h-6 px-2 text-xs"
              @click="showHistory = false"
            >
              <X class="size-3" />
            </Button>
          </div>
        </div>
        <ul class="space-y-0">
          <li
            v-for="ev in filteredHistory"
            :key="ev.id"
            class="border-b border-border/40 last:border-b-0"
          >
            <button
              type="button"
              class="group flex w-full flex-wrap items-center gap-2 py-1.5 text-left text-xs transition-colors hover:bg-muted/40"
              :class="expandedHistoryId === ev.id ? 'bg-muted/40' : ''"
              @click="toggleExpand(ev.id)"
            >
              <ChevronDown
                class="size-3 shrink-0 text-muted-foreground transition-transform"
                :class="expandedHistoryId === ev.id ? 'rotate-0' : '-rotate-90'"
              />
              <span
                class="rounded-full px-1.5 py-0.5 text-[10px] font-semibold leading-none"
                :class="styleFor(ev.severity).pill"
              >
                {{ severityLabel(ev.severity) }}
              </span>
              <span class="font-medium">{{ ruleLabel(ev) }}</span>
              <span class="text-muted-foreground">
                {{ durationLabel(ev.fired_at) }} →
                <template v-if="ev.resolved_at">
                  {{ durationLabel(ev.resolved_at) }} 已解除
                </template>
                <template v-else>仍在進行中</template>
              </span>
              <span
                v-if="ev.acknowledged_at"
                class="inline-flex items-center gap-1 text-[10px] text-muted-foreground"
              >
                <CheckCircle2 class="size-3" />
                已確認
              </span>
            </button>
            <div
              v-if="expandedHistoryId === ev.id"
              class="mb-2 ml-5 rounded-md bg-muted/30 px-3 py-2 text-[11px]"
            >
              <p class="mb-2 text-muted-foreground">{{ ev.description }}</p>
              <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <div class="space-y-1">
                  <div class="flex items-center gap-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                    <Target class="size-3" />
                    觸發條件
                  </div>
                  <p class="font-mono text-[11px]">
                    {{ ev.metric_path }}
                    <span class="text-muted-foreground">{{ ev.comparator }}</span>
                    {{ ev.threshold }}
                  </p>
                  <p
                    v-if="ev.trigger_value !== null"
                    class="text-[11px]"
                  >
                    觸發時的值：<span class="font-mono">{{ ev.trigger_value }}</span>
                  </p>
                  <p
                    v-if="formatContext(ev.context) !== '—'"
                    class="font-mono text-[10px] text-muted-foreground"
                  >
                    context · {{ formatContext(ev.context) }}
                  </p>
                </div>
                <div class="space-y-1">
                  <div class="flex items-center gap-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                    <Timer class="size-3" />
                    時間軸
                  </div>
                  <p>起始：{{ formatDateTime(ev.fired_at) }}</p>
                  <p v-if="ev.resolved_at">
                    解除：{{ formatDateTime(ev.resolved_at) }}
                  </p>
                  <p class="text-muted-foreground">
                    持續：{{ formatDuration(ev.fired_at, ev.resolved_at) }}
                  </p>
                  <p
                    v-if="ev.acknowledged_at"
                    class="text-muted-foreground"
                  >
                    確認於：{{ formatDateTime(ev.acknowledged_at) }}
                  </p>
                </div>
              </div>
              <div class="mt-2 flex justify-end">
                <Button
                  variant="ghost"
                  size="sm"
                  class="h-6 gap-1 text-[11px]"
                  @click.stop="jumpToTrend(ev.metric_path)"
                >
                  查看相關趨勢
                  <ArrowRight class="size-3" />
                </Button>
              </div>
            </div>
          </li>
          <li
            v-if="filteredHistory.length === 0"
            class="py-2 text-center text-xs text-muted-foreground"
          >
            <template v-if="alerts.history.length === 0">尚無歷史</template>
            <template v-else>沒有符合篩選條件的紀錄</template>
          </li>
        </ul>
      </div>
    </CardContent>
  </Card>
</template>

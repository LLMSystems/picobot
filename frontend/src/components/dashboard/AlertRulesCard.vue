<script setup lang="ts">
// Collapsible list of configured alert rules. Default collapsed; the header
// stays visible with a quick summary (total / firing / silenced) so users
// can scan key state without expanding.
import { computed, ref } from 'vue'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  AlertTriangle,
  BellOff,
  BellRing,
  ChevronDown,
  Settings2,
  Zap,
} from 'lucide-vue-next'
import { useAlertsStore } from '@/stores/alerts'
import { relativeTime } from '@/lib/format'
import type { AlertRule, AlertSeverity } from '@/lib/types'

const alerts = useAlertsStore()
const expanded = ref(false)

const SEVERITY_STYLES: Record<
  AlertSeverity,
  { pill: string; dot: string }
> = {
  critical: {
    pill: 'bg-rose-500/15 text-rose-700 dark:text-rose-300',
    dot: 'bg-rose-500',
  },
  warning: {
    pill: 'bg-amber-500/15 text-amber-700 dark:text-amber-300',
    dot: 'bg-amber-500',
  },
  info: {
    pill: 'bg-blue-500/15 text-blue-700 dark:text-blue-300',
    dot: 'bg-blue-500',
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

function ruleLabel(r: AlertRule): string {
  return r.display_name || r.name
}

// Rules sorted by severity priority so critical surfaces first.
const orderedRules = computed(() => {
  const order: AlertSeverity[] = ['critical', 'warning', 'info']
  return [...alerts.rules].sort((a, b) => {
    const sa = order.indexOf(a.severity)
    const sb = order.indexOf(b.severity)
    if (sa !== sb) return sa - sb
    return a.name.localeCompare(b.name)
  })
})

// Reverse lookup so each rule row can check if it's currently firing.
const firingByRule = computed(() => {
  const map = new Map<string, { id: number; fired_at: string }>()
  for (const ev of alerts.active) {
    map.set(ev.rule_name, { id: ev.id, fired_at: ev.fired_at })
  }
  return map
})

const firingCount = computed(() => firingByRule.value.size)
const silencedCount = computed(() => Object.keys(alerts.silences).length)
const totalCount = computed(() => alerts.rules.length)

function isFiring(rule: AlertRule): boolean {
  return firingByRule.value.has(rule.name)
}

function silencedUntilLabel(ruleName: string): string | null {
  const iso = alerts.silences[ruleName]
  if (!iso) return null
  return relativeTime(iso) || iso
}

function firingDurationLabel(rule: AlertRule): string | null {
  const entry = firingByRule.value.get(rule.name)
  if (!entry) return null
  return relativeTime(entry.fired_at)
}

const SILENCE_DURATIONS: { label: string; seconds: number }[] = [
  { label: '靜音 1 小時', seconds: 60 * 60 },
  { label: '靜音 6 小時', seconds: 6 * 60 * 60 },
  { label: '靜音 24 小時', seconds: 24 * 60 * 60 },
  { label: '靜音 7 天', seconds: 7 * 24 * 60 * 60 },
]

async function silence(rule: AlertRule, durationSeconds: number) {
  await alerts.silenceRule(rule.name, durationSeconds)
}

async function unsilence(rule: AlertRule) {
  await alerts.unsilenceRule(rule.name)
}

function toggle() {
  expanded.value = !expanded.value
}
</script>

<template>
  <Card class="border-border/60 gap-0 py-0 shadow-none">
    <CardHeader
      class="flex cursor-pointer select-none items-center gap-2 px-4 py-2.5 transition-colors hover:bg-muted/40"
      @click="toggle"
    >
      <div class="flex flex-wrap items-center gap-3">
        <ChevronDown
          class="size-3.5 shrink-0 text-muted-foreground transition-transform"
          :class="expanded ? 'rotate-0' : '-rotate-90'"
        />
        <Settings2 class="size-4 text-muted-foreground" />
        <span class="text-sm font-semibold">告警規則</span>
        <span class="ml-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          <span>{{ totalCount }} 條啟用</span>
          <span aria-hidden="true">·</span>
          <span
            class="inline-flex items-center gap-1"
            :class="firingCount > 0 ? 'text-rose-600 dark:text-rose-400 font-medium' : ''"
          >
            <Zap class="size-3" />
            {{ firingCount }} 條進行中
          </span>
          <span aria-hidden="true">·</span>
          <span
            class="inline-flex items-center gap-1"
            :class="silencedCount > 0 ? 'text-amber-600 dark:text-amber-400 font-medium' : ''"
          >
            <BellOff class="size-3" />
            {{ silencedCount }} 條靜音
          </span>
        </span>
      </div>
    </CardHeader>
    <CardContent v-if="expanded" class="space-y-2 px-4 pt-1 pb-3">
      <p v-if="totalCount === 0" class="py-6 text-center text-xs text-muted-foreground">
        尚未載入規則（或 alerts.yaml 是空的）
      </p>
      <ul v-else class="space-y-1">
        <li
          v-for="rule in orderedRules"
          :key="rule.name"
          class="flex flex-col gap-1 rounded-md border border-border/40 bg-card px-3 py-2"
        >
          <div class="flex flex-wrap items-center gap-2">
            <span
              class="rounded-full px-2 py-0.5 text-[10px] font-semibold leading-none"
              :class="styleFor(rule.severity).pill"
            >
              {{ severityLabel(rule.severity) }}
            </span>
            <span class="text-sm font-medium">{{ ruleLabel(rule) }}</span>
            <span class="font-mono text-[10px] text-muted-foreground">
              {{ rule.name }}
            </span>
            <span
              v-if="isFiring(rule)"
              class="inline-flex items-center gap-1 rounded-full bg-rose-500/15 px-2 py-0.5 text-[10px] font-medium text-rose-700 dark:text-rose-300"
            >
              <Zap class="size-3" />
              進行中 · {{ firingDurationLabel(rule) }}
            </span>
            <span
              v-if="alerts.silences[rule.name]"
              class="inline-flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-700 dark:text-amber-300"
            >
              <BellOff class="size-3" />
              靜音至 {{ silencedUntilLabel(rule.name) }}
            </span>
            <div class="ml-auto flex items-center gap-1">
              <DropdownMenu v-if="!alerts.silences[rule.name]">
                <DropdownMenuTrigger as-child>
                  <Button variant="ghost" size="sm" class="h-7 text-xs">
                    <BellOff class="size-3" />
                    靜音
                    <ChevronDown class="size-3" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" class="w-40">
                  <DropdownMenuItem
                    v-for="opt in SILENCE_DURATIONS"
                    :key="opt.seconds"
                    @click="silence(rule, opt.seconds)"
                  >
                    <span class="text-sm">{{ opt.label }}</span>
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <Button
                v-else
                variant="ghost"
                size="sm"
                class="h-7 text-xs"
                @click="unsilence(rule)"
              >
                <BellRing class="size-3" />
                取消靜音
              </Button>
            </div>
          </div>
          <p class="text-xs text-muted-foreground">{{ rule.description }}</p>
          <p class="font-mono text-[11px] text-muted-foreground">
            <AlertTriangle class="mr-1 inline-block size-3 align-text-bottom" />
            {{ rule.metric_path }}
            <span class="text-foreground">{{ rule.comparator }}</span>
            {{ rule.threshold }}
            <span v-if="rule.for_seconds > 0" class="ml-1">
              · 持續 {{ rule.for_seconds }} 秒
            </span>
          </p>
        </li>
      </ul>
    </CardContent>
  </Card>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { Skeleton } from '@/components/ui/skeleton'
import {
  MessagesSquare,
  Repeat,
  Wrench,
  CheckCheck,
  Bot,
  Check,
  ChevronsUpDown,
  CircleCheck,
  Coins,
  HardDrive,
  FocusIcon,
} from 'lucide-vue-next'
import { useMetricsStore } from '@/stores/metrics'
import { useSessionsStore } from '@/stores/sessions'
import { formatBytes, formatNumber, formatPercent } from './format'
import { accent } from './colors'
import { metricAccent } from './metricAccents'
import StatCard from './StatCard.vue'
import BarChart from './BarChart.vue'

const metrics = useMetricsStore()
const sessions = useSessionsStore()
const selected = ref<string | null>(null)
const pickerOpen = ref(false)

// All sessions, sorted by recent activity. Search happens inside the
// Command palette — no need to cap the list here.
const options = computed(() => {
  return [...sessions.list].sort((a, b) =>
    (b.updated_at || '').localeCompare(a.updated_at || ''),
  )
})

const selectedSession = computed(() =>
  selected.value ? sessions.findById(selected.value) : undefined,
)

function pickSession(id: string) {
  selected.value = id
  pickerOpen.value = false
}

onMounted(async () => {
  if (!sessions.loaded) await sessions.fetchAll()
})

watch(
  () => sessions.loaded,
  (ok) => {
    if (ok && selected.value === null && options.value.length > 0) {
      selected.value = options.value[0]?.session_id ?? null
    }
  },
  { immediate: true },
)

// `immediate: true` is important: when this component re-mounts (e.g. user
// navigates Chat → Dashboard a second time) `sessions.loaded` is already
// true, so the auto-select watch above fires synchronously during setup
// AND sets `selected` BEFORE this watch is registered. Without immediate,
// we'd miss that initial value and never call loadSession → the picker
// shows a session but the detail panel says "請先選擇一個 session".
watch(
  selected,
  async (id) => {
    if (!id) {
      metrics.clearSessionDetail()
      return
    }
    await metrics.loadSession(id)
  },
  { immediate: true },
)

const detail = computed(() => metrics.sessionDetail)
const workspaceLabel = computed(() => {
  const d = detail.value
  if (!d || d.workspace_bytes === null || d.workspace_bytes === undefined) {
    return '尚未測量'
  }
  return formatBytes(d.workspace_bytes)
})

const toolBars = computed(() => {
  const tools = detail.value?.tool_breakdown ?? []
  return tools.map((t) => ({
    label: t.name,
    value: t.count,
    hint: `成功率 ${formatPercent(t.success_rate)} · ${t.success} 成功 / ${t.failure} 失敗`,
  }))
})
</script>

<template>
  <Card class="border-border/60 shadow-none">
    <CardHeader class="gap-2 pb-3">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <CardTitle class="flex items-center gap-2 text-base">
          <FocusIcon
            class="size-4"
            :style="{ color: accent(metricAccent('sessions')).hexLine }"
          />
          單一 Session 深入分析
        </CardTitle>
        <Popover v-model:open="pickerOpen">
          <PopoverTrigger as-child>
            <Button
              variant="outline"
              role="combobox"
              :aria-expanded="pickerOpen"
              class="h-8 w-[260px] justify-between text-xs font-normal"
            >
              <span class="truncate">
                {{ selectedSession?.title || selectedSession?.session_id || '選一個 session' }}
              </span>
              <ChevronsUpDown class="ml-2 size-3.5 shrink-0 opacity-50" />
            </Button>
          </PopoverTrigger>
          <PopoverContent class="w-[300px] p-0" align="end">
            <Command>
              <CommandInput placeholder="搜尋 session…" class="h-8 text-xs" />
              <CommandList>
                <CommandEmpty class="py-4 text-center text-xs text-muted-foreground">
                  找不到符合的 session
                </CommandEmpty>
                <CommandGroup>
                  <CommandItem
                    v-for="s in options"
                    :key="s.session_id"
                    :value="`${s.title} ${s.session_id}`"
                    class="text-xs"
                    @select="pickSession(s.session_id)"
                  >
                    <Check
                      class="mr-2 size-3.5"
                      :class="selected === s.session_id ? 'opacity-100' : 'opacity-0'"
                    />
                    <span class="truncate">{{ s.title || s.session_id }}</span>
                  </CommandItem>
                </CommandGroup>
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>
      </div>
    </CardHeader>
    <CardContent class="space-y-4">
      <template v-if="metrics.loadingSession">
        <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Skeleton v-for="i in 8" :key="i" class="h-[88px] w-full" />
        </div>
      </template>
      <template v-else-if="metrics.lastSessionError">
        <p class="text-xs text-destructive">
          載入失敗：{{ metrics.lastSessionError.message }}
        </p>
      </template>
      <template v-else-if="!detail">
        <p class="text-xs text-muted-foreground">請先選擇一個 session</p>
      </template>
      <template v-else>
        <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard
            label="訊息數"
            :value="formatNumber(detail.message_count)"
            :icon="MessagesSquare"
            :color="metricAccent('sessions')"
          />
          <StatCard
            label="Assistant 輪數"
            :value="formatNumber(detail.iterations_total)"
            :icon="Repeat"
            :color="metricAccent('iterations')"
          />
          <StatCard
            label="工具呼叫"
            :value="formatNumber(detail.tool_calls_total)"
            :icon="Wrench"
            :color="metricAccent('tool_calls')"
          />
          <StatCard
            label="工具成功率"
            :value="formatPercent(detail.tool_success_rate)"
            :icon="CheckCheck"
            :color="metricAccent('tool_success')"
          />
          <StatCard
            label="子代理執行次數"
            :value="formatNumber(detail.subagent_runs)"
            :icon="Bot"
            :color="metricAccent('subagent_runs')"
          />
          <StatCard
            label="子代理成功 / 失敗"
            :value="`${detail.subagent_success} / ${detail.subagent_failure}`"
            :icon="CircleCheck"
            :color="metricAccent('subagent_success')"
          />
          <StatCard
            label="Tokens（輸入 / 輸出，24h）"
            :value="`${formatNumber(detail.chat_tokens_in)} / ${formatNumber(detail.chat_tokens_out)}`"
            :icon="Coins"
            :color="metricAccent('tokens_in')"
          />
          <StatCard
            label="Workspace 磁碟"
            :value="workspaceLabel"
            :icon="HardDrive"
            :color="metricAccent('workspace')"
          />
        </div>
        <Card v-if="detail.tool_breakdown.length" class="border-border/60 shadow-none">
          <CardHeader class="pb-2">
            <CardTitle class="flex items-center gap-2 text-sm">
              <Wrench
                class="size-3.5"
                :style="{ color: accent(metricAccent('tool_calls')).hexLine }"
              />
              工具使用分佈
            </CardTitle>
          </CardHeader>
          <CardContent>
            <BarChart
              :items="toolBars"
              :accent="metricAccent('tool_calls')"
              show-percent
            />
          </CardContent>
        </Card>
      </template>
    </CardContent>
  </Card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'
import { graphic } from 'echarts'
import { ensureEchartsRegistered } from './echartsSetup'
import { accent, type AccentColor } from './colors'
import type { MetricsHistorySeries } from '@/lib/types'

ensureEchartsRegistered()

const props = defineProps<{
  title?: string
  series: MetricsHistorySeries[]
  height?: number
  yFormatter?: (value: number) => string
  smooth?: boolean
  /** When true (default for percentage-like series), Y axis is bounded to [0,1]. */
  asPercent?: boolean
  /** Optional accent — line + area colour for the first series. */
  accent?: AccentColor
  /** Additional palette overrides for series 2..n (uses default echarts colours otherwise). */
  extraAccents?: AccentColor[]
}>()

function paletteFor(index: number): { line: string; area: string } | null {
  if (index === 0 && props.accent) {
    const a = accent(props.accent)
    return { line: a.hexLine, area: a.hexArea }
  }
  if (index > 0 && props.extraAccents && index - 1 < props.extraAccents.length) {
    const a = accent(props.extraAccents[index - 1]!)
    return { line: a.hexLine, area: a.hexArea }
  }
  return null
}

const option = computed<EChartsOption>(() => {
  const seriesNames = props.series.map((s) =>
    s.dim_value ? `${s.metric} · ${s.dim_value}` : s.metric,
  )

  return {
    grid: { left: 48, right: 12, top: 24, bottom: 28 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line' },
      valueFormatter: (value) => {
        if (value === null || value === undefined) return '—'
        if (props.yFormatter) return props.yFormatter(Number(value))
        return Number(value).toLocaleString()
      },
    },
    legend: seriesNames.length > 1
      ? { top: 0, type: 'scroll', textStyle: { fontSize: 11 } }
      : undefined,
    xAxis: {
      type: 'time',
      axisLabel: { fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      ...(props.asPercent ? { min: 0, max: 1 } : {}),
      axisLabel: {
        fontSize: 10,
        formatter: (value: number) => {
          if (props.yFormatter) return props.yFormatter(value)
          if (props.asPercent) return `${(value * 100).toFixed(0)}%`
          if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
          if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}K`
          return String(value)
        },
      },
    },
    series: props.series.map((s, i) => {
      const palette = paletteFor(i)
      return {
        name: seriesNames[i],
        type: 'line',
        smooth: props.smooth ?? true,
        showSymbol: false,
        lineStyle: palette ? { color: palette.line, width: 2 } : { width: 2 },
        itemStyle: palette ? { color: palette.line } : undefined,
        // Only fill the area for the first series — multi-series area stacks
        // get muddy visually.
        areaStyle:
          palette && i === 0
            ? {
                color: new graphic.LinearGradient(0, 0, 0, 1, [
                  { offset: 0, color: palette.area },
                  { offset: 1, color: 'rgba(0,0,0,0)' },
                ]),
              }
            : undefined,
        data: s.points.map((p) => [p.ts, p.value]),
      }
    }),
  }
})

const isEmpty = computed(() =>
  props.series.every((s) => s.points.length === 0),
)

const resolvedHeight = computed(() => props.height ?? 240)
</script>

<template>
  <div class="space-y-1">
    <div v-if="title" class="text-sm font-medium">{{ title }}</div>
    <div
      v-if="isEmpty"
      class="flex items-center justify-center rounded border border-dashed text-xs text-muted-foreground"
      :style="{ height: `${resolvedHeight}px` }"
    >
      尚無資料 — snapshot 任務需要先寫入幾個點
    </div>
    <VChart
      v-else
      :option="option"
      :style="{ height: `${resolvedHeight}px`, width: '100%' }"
      autoresize
    />
  </div>
</template>

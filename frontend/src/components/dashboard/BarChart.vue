<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'
import { graphic } from 'echarts'
import { ensureEchartsRegistered } from './echartsSetup'
import { accent, type AccentColor } from './colors'

ensureEchartsRegistered()

export interface BarItem {
  label: string
  value: number
  /** Optional second value — when any item provides this, the chart renders
   *  a stacked horizontal bar (primary | secondary) so two related metrics
   *  share one row (e.g. tokens in vs out per model). */
  secondary?: number
  /** Optional extra text shown in tooltip footer. */
  hint?: string
}

const props = defineProps<{
  items: BarItem[]
  accent?: AccentColor
  /** Used for the secondary stack — required when any item provides `secondary`. */
  secondaryAccent?: AccentColor
  /** Legend names for the two stacks. Falls back to "主" / "副". */
  primaryLabel?: string
  secondaryLabel?: string
  height?: number
  /** When true, appends "(xx%)" to the value label. */
  showPercent?: boolean
  /** When true (default), shows the value label at the bar end. */
  showValue?: boolean
  valueFormatter?: (value: number) => string
}>()

const palette = computed(() => accent(props.accent ?? 'blue'))
const secondaryPalette = computed(() =>
  accent(props.secondaryAccent ?? 'slate'),
)

const isStacked = computed(() =>
  props.items.some((i) => typeof i.secondary === 'number'),
)

const totalValue = computed(() =>
  props.items.reduce((sum, item) => {
    return sum + (item.value || 0) + (item.secondary || 0)
  }, 0),
)

function formatValue(v: number): string {
  if (props.valueFormatter) return props.valueFormatter(v)
  return v.toLocaleString()
}

const option = computed<EChartsOption>(() => {
  // Reverse so the largest bar sits at the top — echarts category axis stacks
  // categories bottom-up by default.
  const ordered = [...props.items].sort(
    (a, b) =>
      (b.value || 0) + (b.secondary || 0) - ((a.value || 0) + (a.secondary || 0)),
  )
  const visible = ordered.slice(0, 8).reverse()
  const categories = visible.map((i) => i.label)
  const primaryValues = visible.map((i) => i.value)
  const secondaryValues = visible.map((i) => i.secondary ?? 0)
  const total = totalValue.value
  const showValue = props.showValue !== false

  function buildLabel(v: number): string {
    const parts: string[] = []
    if (showValue) parts.push(formatValue(v))
    if (props.showPercent && total > 0) {
      parts.push(`${((v / total) * 100).toFixed(0)}%`)
    }
    return parts.join(' ')
  }

  return {
    grid: {
      left: 8,
      right: 64,
      top: isStacked.value ? 24 : 8,
      bottom: 8,
      containLabel: true,
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const arr = Array.isArray(params) ? params : [params]
        const first = arr[0]
        const item = visible[first.dataIndex]
        if (!item) return ''
        const primary = item.value || 0
        const secondary = item.secondary ?? null
        const sum = primary + (secondary ?? 0)
        const pct =
          total > 0 ? ` · ${((sum / total) * 100).toFixed(1)} %` : ''
        const lines: string[] = [
          `<div style="font-weight:600">${first.name}</div>`,
        ]
        if (secondary !== null) {
          lines.push(
            `<div>${props.primaryLabel ?? '主'}：${formatValue(primary)}</div>`,
          )
          lines.push(
            `<div>${props.secondaryLabel ?? '副'}：${formatValue(secondary)}</div>`,
          )
          lines.push(`<div>合計：${formatValue(sum)}${pct}</div>`)
        } else {
          lines.push(`<div>${formatValue(primary)}${pct}</div>`)
        }
        if (item.hint) {
          lines.push(`<div style="color:#888;font-size:11px">${item.hint}</div>`)
        }
        return lines.join('')
      },
    },
    legend: isStacked.value
      ? {
          top: 0,
          right: 0,
          textStyle: { fontSize: 11 },
          data: [
            props.primaryLabel ?? '主',
            props.secondaryLabel ?? '副',
          ],
        }
      : undefined,
    xAxis: {
      type: 'value',
      show: false,
    },
    yAxis: {
      type: 'category',
      data: categories,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        fontSize: 11,
        formatter: (name: string) =>
          name.length > 22 ? `${name.slice(0, 21)}…` : name,
      },
    },
    series: isStacked.value
      ? [
          {
            name: props.primaryLabel ?? '主',
            type: 'bar',
            stack: 'total',
            data: primaryValues,
            barWidth: 14,
            itemStyle: {
              borderRadius: [4, 0, 0, 4],
              color: new graphic.LinearGradient(0, 0, 1, 0, [
                { offset: 0, color: palette.value.hexArea },
                { offset: 1, color: palette.value.hexLine },
              ]),
            },
            label: { show: false },
          },
          {
            name: props.secondaryLabel ?? '副',
            type: 'bar',
            stack: 'total',
            data: secondaryValues,
            barWidth: 14,
            itemStyle: {
              borderRadius: [0, 4, 4, 0],
              color: new graphic.LinearGradient(0, 0, 1, 0, [
                { offset: 0, color: secondaryPalette.value.hexArea },
                { offset: 1, color: secondaryPalette.value.hexLine },
              ]),
            },
            label: {
              show: showValue || props.showPercent,
              position: 'right',
              fontSize: 10,
              color: '#888',
              formatter: (params: any) => {
                const item = visible[params.dataIndex]
                if (!item) return ''
                const sum = (item.value || 0) + (item.secondary || 0)
                return buildLabel(sum)
              },
            },
          },
        ]
      : [
          {
            type: 'bar',
            data: primaryValues,
            barWidth: 14,
            itemStyle: {
              borderRadius: [0, 4, 4, 0],
              color: new graphic.LinearGradient(0, 0, 1, 0, [
                { offset: 0, color: palette.value.hexArea },
                { offset: 1, color: palette.value.hexLine },
              ]),
            },
            label:
              showValue || props.showPercent
                ? {
                    show: true,
                    position: 'right',
                    fontSize: 10,
                    color: '#888',
                    formatter: (params: any) => buildLabel(Number(params.value)),
                  }
                : { show: false },
          },
        ],
  }
})

const isEmpty = computed(() => props.items.length === 0)
const resolvedHeight = computed(() => {
  const base = isStacked.value ? 56 : 32
  return props.height ?? base + props.items.length * 28
})
</script>

<template>
  <div
    v-if="isEmpty"
    class="flex items-center justify-center rounded border border-dashed text-xs text-muted-foreground"
    :style="{ height: `${resolvedHeight}px` }"
  >
    尚無資料
  </div>
  <VChart
    v-else
    :option="option"
    :style="{ height: `${resolvedHeight}px`, width: '100%' }"
    autoresize
  />
</template>

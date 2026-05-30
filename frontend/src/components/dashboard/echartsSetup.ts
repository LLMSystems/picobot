// Tree-shaken echarts registry. Only the chart types and components used by
// the dashboard are pulled in, so the lazy dashboard chunk stays small.
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  TitleComponent,
} from 'echarts/components'

let registered = false

export function ensureEchartsRegistered(): void {
  if (registered) return
  use([
    CanvasRenderer,
    LineChart,
    BarChart,
    GridComponent,
    TooltipComponent,
    LegendComponent,
    DataZoomComponent,
    TitleComponent,
  ])
  registered = true
}

import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api, API_BASE } from '@/lib/api'
import { ApiError } from '@/lib/errors'
import type {
  MetricsCurrentSnapshot,
  MetricsHistoryResponse,
  MetricsRange,
  MetricsSessionSnapshot,
} from '@/lib/types'

// While SSE is connected we don't need to poll the current snapshot — the
// server pushes it every 10s. The interval stays running for `history` only.
const POLL_INTERVAL_MS = 30_000
const SSE_OPEN_TIMEOUT_MS = 5_000

const HISTORY_SERIES: string[] = [
  'cpu_percent',
  'rss_bytes',
  'tokens_in_24h',
  'tokens_out_24h',
  'tool_calls_total',
  'qps_1m',
  'latency_p95_ms',
  'error_4xx_rate_1h',
  'error_5xx_rate_1h',
  'runs_24h',
  'duration_p95_ms',
  // llm metrics — share names with api (latency_p95_ms / error_rate) but
  // live in a separate `llm` category; consumers filter via findSeries(..., 'llm').
  'ttft_p95_ms',
  'iterations_per_chat_avg',
]

function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err
  const message = err instanceof Error ? err.message : String(err)
  return new ApiError('UNKNOWN', message || '請求失敗')
}

export const useMetricsStore = defineStore('metrics', () => {
  const current = ref<MetricsCurrentSnapshot | null>(null)
  const sessionDetail = ref<MetricsSessionSnapshot | null>(null)
  const history = ref<MetricsHistoryResponse | null>(null)
  const historyRange = ref<MetricsRange>('24h')
  const loading = ref(false)
  const loadingHistory = ref(false)
  const loadingSession = ref(false)
  const lastError = ref<ApiError | null>(null)
  const lastHistoryError = ref<ApiError | null>(null)
  const lastSessionError = ref<ApiError | null>(null)
  const lastFetchedAt = ref<number | null>(null)
  const liveConnected = ref(false)
  const liveLastEventAt = ref<number | null>(null)
  let pollTimer: number | null = null
  let pollers = 0
  let sse: EventSource | null = null
  let sseOpenTimer: number | null = null

  async function refreshCurrent(): Promise<void> {
    loading.value = true
    lastError.value = null
    try {
      current.value = await api.metricsCurrent()
      lastFetchedAt.value = Date.now()
    } catch (err) {
      lastError.value = toApiError(err)
    } finally {
      loading.value = false
    }
  }

  async function loadSession(sessionId: string): Promise<void> {
    loadingSession.value = true
    lastSessionError.value = null
    try {
      sessionDetail.value = await api.metricsSession(sessionId)
    } catch (err) {
      lastSessionError.value = toApiError(err)
      sessionDetail.value = null
    } finally {
      loadingSession.value = false
    }
  }

  function clearSessionDetail(): void {
    sessionDetail.value = null
    lastSessionError.value = null
  }

  async function refreshHistory(range: MetricsRange = historyRange.value): Promise<void> {
    historyRange.value = range
    loadingHistory.value = true
    lastHistoryError.value = null
    try {
      history.value = await api.metricsHistory({
        range,
        series: HISTORY_SERIES,
      })
    } catch (err) {
      lastHistoryError.value = toApiError(err)
    } finally {
      loadingHistory.value = false
    }
  }

  function findSeries(
    metric: string,
    dimValue?: string | null,
    category?: string,
  ) {
    if (!history.value) return null
    return (
      history.value.series.find(
        (s) =>
          s.metric === metric &&
          (dimValue === undefined || s.dim_value === dimValue) &&
          (category === undefined || s.category === category),
      ) ?? null
    )
  }

  function findAllSeries(metric: string, category?: string) {
    if (!history.value) return []
    return history.value.series.filter(
      (s) => s.metric === metric && (category === undefined || s.category === category),
    )
  }

  function connectLive(): void {
    if (sse !== null) return
    let opened = false
    try {
      const url = `${API_BASE}/metrics/stream`
      const es = new EventSource(url, { withCredentials: true })
      sse = es

      es.addEventListener('metrics_snapshot', (raw) => {
        const me = raw as MessageEvent
        try {
          const payload = JSON.parse(me.data) as MetricsCurrentSnapshot
          current.value = payload
          lastFetchedAt.value = Date.now()
          liveLastEventAt.value = Date.now()
          opened = true
          liveConnected.value = true
          lastError.value = null
        } catch {
          // ignore malformed frame
        }
      })

      es.onerror = () => {
        // EventSource auto-reconnects; we only mark "disconnected" when the
        // browser gives up by setting readyState to CLOSED.
        if (es.readyState === EventSource.CLOSED) {
          liveConnected.value = false
        }
      }

      // If no frame arrives within the open timeout, treat live as failed
      // and fall back to polling (which is always running anyway).
      sseOpenTimer = window.setTimeout(() => {
        if (!opened) {
          liveConnected.value = false
        }
      }, SSE_OPEN_TIMEOUT_MS)
    } catch {
      liveConnected.value = false
    }
  }

  function disconnectLive(): void {
    if (sseOpenTimer !== null) {
      window.clearTimeout(sseOpenTimer)
      sseOpenTimer = null
    }
    if (sse !== null) {
      sse.close()
      sse = null
    }
    liveConnected.value = false
    liveLastEventAt.value = null
  }

  // Reference-counted lifecycle: every active DashboardView mount registers
  // once. Polling runs as a fallback alongside the SSE connection; both stay
  // alive only while at least one consumer is mounted.
  function startPolling(): void {
    pollers += 1
    if (pollers === 1) {
      void refreshCurrent()
      void refreshHistory(historyRange.value)
      connectLive()
      pollTimer = window.setInterval(() => {
        // Skip polling `current` when live is healthy (fresh push within 2x
        // tick); the history endpoint still needs the periodic refresh.
        const liveFresh =
          liveConnected.value &&
          liveLastEventAt.value !== null &&
          Date.now() - liveLastEventAt.value < 25_000
        if (!liveFresh) {
          void refreshCurrent()
        }
        void refreshHistory(historyRange.value)
      }, POLL_INTERVAL_MS)
    }
  }

  function stopPolling(): void {
    pollers = Math.max(0, pollers - 1)
    if (pollers === 0) {
      if (pollTimer !== null) {
        window.clearInterval(pollTimer)
        pollTimer = null
      }
      disconnectLive()
    }
  }

  const isReady = computed(() => current.value !== null)

  return {
    current,
    sessionDetail,
    history,
    historyRange,
    loading,
    loadingHistory,
    loadingSession,
    lastError,
    lastHistoryError,
    lastSessionError,
    lastFetchedAt,
    liveConnected,
    liveLastEventAt,
    isReady,
    refreshCurrent,
    refreshHistory,
    findSeries,
    findAllSeries,
    loadSession,
    clearSessionDetail,
    startPolling,
    stopPolling,
  }
})

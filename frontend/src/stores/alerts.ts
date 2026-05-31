import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api, API_BASE } from '@/lib/api'
import { ApiError } from '@/lib/errors'
import { useNotifications } from '@/composables/useNotifications'
import type {
  AlertEvent,
  AlertRule,
  AlertSeverity,
} from '@/lib/types'

// Polling acts as a fallback when SSE isn't healthy. While the live stream is
// pushing, the interval just re-syncs every 60s in case of dropped frames.
const POLL_INTERVAL_MS = 60_000

function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err
  const message = err instanceof Error ? err.message : String(err)
  return new ApiError('UNKNOWN', message || '請求失敗')
}

const NOTIFICATION_SEVERITIES: AlertSeverity[] = ['warning', 'critical']

export const useAlertsStore = defineStore('alerts', () => {
  const active = ref<AlertEvent[]>([])
  const history = ref<AlertEvent[]>([])
  const silences = ref<Record<string, string>>({})
  const rules = ref<AlertRule[]>([])
  const loading = ref(false)
  const lastError = ref<ApiError | null>(null)

  let pollTimer: number | null = null
  let pollers = 0
  let sse: EventSource | null = null
  let sseOpenTimer: number | null = null
  const liveConnected = ref(false)
  const liveLastEventAt = ref<number | null>(null)

  // Track which event ids we've already alerted on so we don't re-notify
  // every poll while the alert is still firing.
  const notifiedEventIds = new Set<number>()

  function severityLabel(severity: AlertSeverity): string {
    if (severity === 'critical') return '嚴重'
    if (severity === 'warning') return '警告'
    return '提示'
  }

  function maybeNotify(ev: AlertEvent, previouslyKnown: Set<number>): void {
    if (notifiedEventIds.has(ev.id)) return
    if (previouslyKnown.has(ev.id)) {
      notifiedEventIds.add(ev.id)
      return
    }
    notifiedEventIds.add(ev.id)
    if (!NOTIFICATION_SEVERITIES.includes(ev.severity)) return
    const notifs = useNotifications()
    const label = ev.display_name || ev.rule_name
    notifs.notifyAlert({
      title: `【${severityLabel(ev.severity)}】${label}`,
      body: ev.description,
      tag: `picobot-alert-${ev.id}`,
    })
  }

  async function refresh(): Promise<void> {
    loading.value = true
    lastError.value = null
    try {
      const resp = await api.alertsActive()
      const previouslyKnown = new Set(active.value.map((e) => e.id))
      active.value = resp.items
      silences.value = resp.silences

      // Browser-notify any newly-firing event of warning or higher severity.
      for (const ev of resp.items) {
        maybeNotify(ev, previouslyKnown)
      }
    } catch (err) {
      lastError.value = toApiError(err)
    } finally {
      loading.value = false
    }
  }

  async function refreshHistory(limit: number = 100): Promise<void> {
    try {
      const resp = await api.alertsHistory({ limit })
      history.value = resp.items
    } catch (err) {
      lastError.value = toApiError(err)
    }
  }

  async function loadRules(): Promise<void> {
    try {
      const resp = await api.alertsRules()
      rules.value = resp.rules
    } catch (err) {
      lastError.value = toApiError(err)
    }
  }

  async function acknowledge(eventId: number): Promise<void> {
    try {
      await api.ackAlert(eventId)
      const found = active.value.find((e) => e.id === eventId)
      if (found) found.acknowledged_at = new Date().toISOString()
    } catch (err) {
      lastError.value = toApiError(err)
    }
  }

  async function silenceRule(
    ruleName: string,
    durationSeconds: number,
  ): Promise<void> {
    try {
      const resp = await api.silenceAlertRule(ruleName, durationSeconds)
      silences.value = { ...silences.value, [ruleName]: resp.silenced_until }
    } catch (err) {
      lastError.value = toApiError(err)
    }
  }

  async function unsilenceRule(ruleName: string): Promise<void> {
    try {
      await api.unsilenceAlertRule(ruleName)
      const next = { ...silences.value }
      delete next[ruleName]
      silences.value = next
    } catch (err) {
      lastError.value = toApiError(err)
    }
  }

  // ---- SSE wiring --------------------------------------------------------

  function applySnapshot(items: AlertEvent[], silenceMap: Record<string, string>) {
    const previouslyKnown = new Set(active.value.map((e) => e.id))
    active.value = items
    silences.value = silenceMap
    for (const ev of items) {
      maybeNotify(ev, previouslyKnown)
    }
  }

  function upsertActive(event: AlertEvent) {
    const idx = active.value.findIndex((e) => e.id === event.id)
    if (idx >= 0) {
      const next = [...active.value]
      next.splice(idx, 1, event)
      active.value = next
    } else {
      active.value = [event, ...active.value]
    }
  }

  function removeActive(id: number) {
    active.value = active.value.filter((e) => e.id !== id)
  }

  function connectLive(): void {
    if (sse !== null) return
    let opened = false
    try {
      const es = new EventSource(`${API_BASE}/alerts/stream`, { withCredentials: false })
      sse = es

      es.addEventListener('alert_snapshot', (raw) => {
        const me = raw as MessageEvent
        try {
          const payload = JSON.parse(me.data) as {
            items: AlertEvent[]
            silences: Record<string, string>
          }
          applySnapshot(payload.items ?? [], payload.silences ?? {})
          opened = true
          liveConnected.value = true
          liveLastEventAt.value = Date.now()
        } catch {
          // ignore
        }
      })

      es.addEventListener('alert_fired', (raw) => {
        const me = raw as MessageEvent
        try {
          const event = JSON.parse(me.data) as AlertEvent
          const previouslyKnown = new Set(active.value.map((e) => e.id))
          upsertActive(event)
          maybeNotify(event, previouslyKnown)
          liveLastEventAt.value = Date.now()
        } catch {
          // ignore
        }
      })

      es.addEventListener('alert_resolved', (raw) => {
        const me = raw as MessageEvent
        try {
          const event = JSON.parse(me.data) as AlertEvent
          removeActive(event.id)
          liveLastEventAt.value = Date.now()
        } catch {
          // ignore
        }
      })

      es.addEventListener('alert_acknowledged', (raw) => {
        const me = raw as MessageEvent
        try {
          const event = JSON.parse(me.data) as AlertEvent
          upsertActive(event)
          liveLastEventAt.value = Date.now()
        } catch {
          // ignore
        }
      })

      es.addEventListener('alert_silenced', (raw) => {
        const me = raw as MessageEvent
        try {
          const data = JSON.parse(me.data) as { rule_name: string; silenced_until: string }
          silences.value = { ...silences.value, [data.rule_name]: data.silenced_until }
          liveLastEventAt.value = Date.now()
        } catch {
          // ignore
        }
      })

      es.addEventListener('alert_unsilenced', (raw) => {
        const me = raw as MessageEvent
        try {
          const data = JSON.parse(me.data) as { rule_name: string }
          const next = { ...silences.value }
          delete next[data.rule_name]
          silences.value = next
          liveLastEventAt.value = Date.now()
        } catch {
          // ignore
        }
      })

      es.onerror = () => {
        if (es.readyState === EventSource.CLOSED) {
          liveConnected.value = false
        }
      }

      // If no event arrives within 5s, treat live as not-yet-ready; polling
      // fallback continues regardless.
      sseOpenTimer = window.setTimeout(() => {
        if (!opened) liveConnected.value = false
      }, 5_000)
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

  function startPolling(): void {
    pollers += 1
    if (pollers === 1) {
      void refresh()
      void loadRules()
      connectLive()
      pollTimer = window.setInterval(() => {
        // Skip polling when live recently delivered an event; just keep alive.
        const liveFresh =
          liveConnected.value &&
          liveLastEventAt.value !== null &&
          Date.now() - liveLastEventAt.value < 90_000
        if (!liveFresh) {
          void refresh()
        }
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

  const activeCount = computed(() => active.value.length)
  const criticalCount = computed(
    () => active.value.filter((e) => e.severity === 'critical').length,
  )
  const warningCount = computed(
    () => active.value.filter((e) => e.severity === 'warning').length,
  )
  const highestSeverity = computed<AlertSeverity | null>(() => {
    if (criticalCount.value > 0) return 'critical'
    if (warningCount.value > 0) return 'warning'
    if (active.value.length > 0) return 'info'
    return null
  })

  return {
    active,
    history,
    silences,
    rules,
    loading,
    lastError,
    liveConnected,
    liveLastEventAt,
    activeCount,
    criticalCount,
    warningCount,
    highestSeverity,
    refresh,
    refreshHistory,
    loadRules,
    acknowledge,
    silenceRule,
    unsilenceRule,
    startPolling,
    stopPolling,
  }
})

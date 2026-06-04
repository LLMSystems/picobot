import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/lib/api'
import type {
  McpServerConfig,
  McpServerStatus,
  McpStatusResponse,
} from '@/lib/types'

const POLL_TIMEOUT_MS = 10_000
const POLL_INTERVAL_MS = 400

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export const useMcpStore = defineStore('mcp', () => {
  const status = ref<McpStatusResponse | null>(null)
  const rawServers = ref<Record<string, McpServerConfig>>({})
  const loaded = ref(false)
  const loading = ref(false)
  const reloading = ref(false)
  const mutating = ref(false)
  const error = ref<string | null>(null)

  // After any change the servers connect in a background task, so the immediate
  // response can still report `connecting`. Poll /mcp/status until everything
  // settles (or we hit the timeout) so the UI shows the final state.
  async function pollUntilSettled() {
    const deadline = Date.now() + POLL_TIMEOUT_MS
    while (
      status.value !== null &&
      status.value.connecting_server_count > 0 &&
      Date.now() < deadline
    ) {
      await sleep(POLL_INTERVAL_MS)
      status.value = await api.getMcpStatus()
    }
  }

  async function refresh() {
    loading.value = true
    error.value = null
    try {
      status.value = await api.getMcpStatus()
      loaded.value = true
      if (status.value.reload_supported) {
        rawServers.value = (await api.getMcpServers()).servers
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : '載入 MCP 狀態失敗'
    } finally {
      loading.value = false
    }
  }

  async function load() {
    if (loaded.value) return
    await refresh()
  }

  async function reload() {
    reloading.value = true
    error.value = null
    try {
      status.value = await api.reloadMcp()
      await pollUntilSettled()
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'MCP 重新載入失敗'
    } finally {
      reloading.value = false
    }
  }

  // Persist one server to config.json then reconcile. Throws on failure so the
  // form can keep its draft and surface the message.
  async function upsert(name: string, config: McpServerConfig) {
    mutating.value = true
    error.value = null
    try {
      status.value = await api.upsertMcpServer(name, config)
      rawServers.value = (await api.getMcpServers()).servers
      await pollUntilSettled()
    } finally {
      mutating.value = false
    }
  }

  async function remove(name: string) {
    mutating.value = true
    error.value = null
    try {
      status.value = await api.deleteMcpServer(name)
      rawServers.value = (await api.getMcpServers()).servers
      await pollUntilSettled()
    } finally {
      mutating.value = false
    }
  }

  const supported = computed(() => status.value?.supported ?? false)
  const reloadSupported = computed(() => status.value?.reload_supported ?? false)
  const servers = computed<McpServerStatus[]>(() => status.value?.servers ?? [])
  const connectedCount = computed(() => status.value?.connected_server_count ?? 0)
  const configuredCount = computed(() => status.value?.configured_server_count ?? 0)

  return {
    status,
    rawServers,
    loaded,
    loading,
    reloading,
    mutating,
    error,
    refresh,
    load,
    reload,
    upsert,
    remove,
    supported,
    reloadSupported,
    servers,
    connectedCount,
    configuredCount,
  }
})

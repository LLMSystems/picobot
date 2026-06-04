<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { RefreshCw, Server, Wrench } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { useMcpStore } from '@/stores/mcp'
import type { McpServerStatus } from '@/lib/types'

const mcpStore = useMcpStore()
const {
  loading,
  reloading,
  error,
  supported,
  reloadSupported,
  servers,
  connectedCount,
  configuredCount,
} = storeToRefs(mcpStore)

onMounted(() => {
  void mcpStore.load()
})

function transportLabel(server: McpServerStatus): string {
  switch (server.transport) {
    case 'stdio':
      return 'stdio'
    case 'sse':
      return 'SSE'
    case 'streamableHttp':
      return 'HTTP'
    default:
      return server.transport
  }
}

function stateLabel(server: McpServerStatus): string {
  if (server.error) return '錯誤'
  if (server.connecting) return '連線中'
  if (server.connected) return '已連線'
  return '未連線'
}

const hasServers = computed(() => servers.value.length > 0)
</script>

<template>
  <section class="space-y-3">
    <div class="flex items-center justify-between">
      <div>
        <h3 class="text-sm font-medium">MCP Servers</h3>
        <p class="text-xs text-muted-foreground">
          連線：{{ connectedCount }} / {{ configuredCount }} · 在 config.json 的
          <code>mcpServers</code> 設定後按「重新載入」即可生效
        </p>
      </div>
      <Button
        variant="outline"
        size="sm"
        class="h-7 px-2 text-xs"
        :disabled="!supported || !reloadSupported || reloading"
        :title="
          !reloadSupported ? '未設定 config 檔，無法重新載入' : '重新讀取 config 並重連'
        "
        @click="mcpStore.reload()"
      >
        <RefreshCw class="mr-1 size-3" :class="{ 'animate-spin': reloading }" />
        {{ reloading ? '重新載入中…' : '重新載入' }}
      </Button>
    </div>

    <p
      v-if="error"
      class="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive"
    >
      {{ error }}
    </p>

    <div
      v-if="loading && !mcpStore.loaded"
      class="rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground"
    >
      載入中…
    </div>

    <div
      v-else-if="!supported"
      class="rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground"
    >
      此後端未啟用 MCP。
    </div>

    <div
      v-else-if="!hasServers"
      class="rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground"
    >
      尚未設定任何 MCP server，請在 config.json 的 <code>mcpServers</code> 中設定。
    </div>

    <div v-else class="overflow-hidden rounded-md border bg-muted/30">
      <div class="divide-y">
        <div
          v-for="server in servers"
          :key="server.name"
          class="bg-background px-3 py-2"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-1.5">
                <Server class="size-3 text-muted-foreground" />
                <span class="text-xs font-medium">{{ server.name }}</span>
                <span
                  class="rounded border border-border bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
                >
                  {{ transportLabel(server) }}
                </span>
                <span
                  v-if="server.tool_count > 0"
                  class="text-[10px] text-muted-foreground"
                >
                  {{ server.tool_count }} 個 tool
                </span>
              </div>
              <div
                v-if="server.tool_names.length > 0"
                class="mt-1 flex flex-wrap gap-1"
              >
                <code
                  v-for="name in server.tool_names"
                  :key="name"
                  class="inline-flex items-center gap-0.5 rounded bg-muted px-1 py-0.5 font-mono text-[10px] text-muted-foreground"
                >
                  <Wrench class="size-2.5" />{{ name }}
                </code>
              </div>
              <p
                v-if="server.error"
                class="mt-1 line-clamp-2 text-[11px] text-destructive"
                :title="server.error"
              >
                {{ server.error }}
              </p>
            </div>
            <div class="flex shrink-0 items-center gap-1.5">
              <span
                class="size-2 rounded-full"
                :class="{
                  'bg-emerald-500': server.connected,
                  'animate-pulse bg-amber-500': server.connecting && !server.connected,
                  'bg-destructive': server.error,
                  'bg-muted-foreground/40':
                    !server.connected && !server.connecting && !server.error,
                }"
              />
              <span class="text-[10px] text-muted-foreground">
                {{ stateLabel(server) }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

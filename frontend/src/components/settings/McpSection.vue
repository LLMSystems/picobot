<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { Pencil, Plus, RefreshCw, Server, Trash2, Wrench } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { useMcpStore } from '@/stores/mcp'
import type { McpServerConfig, McpServerStatus, McpTransport } from '@/lib/types'

const mcpStore = useMcpStore()
const {
  loading,
  reloading,
  mutating,
  error,
  supported,
  reloadSupported,
  servers,
  rawServers,
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
const canEdit = computed(() => supported.value && reloadSupported.value)

// ---- create / edit form ----------------------------------------------------

const formOpen = ref(false)
const editingName = ref<string | null>(null)
const submitting = ref(false)
const formError = ref<string | null>(null)

const form = reactive({
  name: '',
  transport: 'stdio' as McpTransport,
  command: '',
  argsText: '',
  envText: '',
  cwd: '',
  url: '',
  headersText: '',
  toolTimeout: 30,
  enabledToolsText: '*',
  includeResources: false,
  includePrompts: false,
})

// Per-tool toggles are only possible once a server is connected, because the
// full tool catalog is discovered at connect time. Fall back to the free-text
// list otherwise (e.g. when creating a brand-new server).
const editingAvailableTools = computed<string[]>(() => {
  if (!editingName.value) return []
  return servers.value.find((s) => s.name === editingName.value)?.available_tools ?? []
})
const useToolCheckboxes = computed(() => editingAvailableTools.value.length > 0)
const toolChecked = reactive<Record<string, boolean>>({})
const allToolsChecked = computed(() =>
  editingAvailableTools.value.every((t) => toolChecked[t]),
)

function toggleAllTools(value: boolean) {
  for (const t of editingAvailableTools.value) toolChecked[t] = value
}

function linesToArray(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
}

function arrayToLines(arr: string[] | undefined): string {
  return (arr ?? []).join('\n')
}

function textToKeyValue(text: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const line of linesToArray(text)) {
    const eq = line.indexOf('=')
    if (eq <= 0) continue
    out[line.slice(0, eq).trim()] = line.slice(eq + 1).trim()
  }
  return out
}

function keyValueToText(obj: Record<string, string> | undefined): string {
  return Object.entries(obj ?? {})
    .map(([k, v]) => `${k}=${v}`)
    .join('\n')
}

function resetForm() {
  form.name = ''
  form.transport = 'stdio'
  form.command = ''
  form.argsText = ''
  form.envText = ''
  form.cwd = ''
  form.url = ''
  form.headersText = ''
  form.toolTimeout = 30
  form.enabledToolsText = '*'
  form.includeResources = false
  form.includePrompts = false
}

function openCreate() {
  resetForm()
  editingName.value = null
  formError.value = null
  formOpen.value = true
}

function openEdit(name: string) {
  const c: McpServerConfig = rawServers.value[name] ?? {}
  editingName.value = name
  formError.value = null
  form.name = name
  form.transport = c.type ?? (c.command ? 'stdio' : 'streamableHttp')
  form.command = c.command ?? ''
  form.argsText = arrayToLines(c.args)
  form.envText = keyValueToText(c.env)
  form.cwd = c.cwd ?? ''
  form.url = c.url ?? ''
  form.headersText = keyValueToText(c.headers)
  form.toolTimeout = c.toolTimeout ?? 30
  form.enabledToolsText = arrayToLines(c.enabledTools) || '*'
  form.includeResources = c.includeResources ?? false
  form.includePrompts = c.includePrompts ?? false
  // Seed the per-tool checkboxes from the saved enabledTools list. Omitted /
  // ["*"] means every tool is enabled; an explicit list enables only those.
  for (const key of Object.keys(toolChecked)) delete toolChecked[key]
  const enabled = c.enabledTools
  const allowAll = !enabled || enabled.includes('*')
  const available = servers.value.find((s) => s.name === name)?.available_tools ?? []
  for (const t of available) {
    toolChecked[t] = allowAll || enabled!.includes(t)
  }
  formOpen.value = true
}

function buildConfig(): McpServerConfig {
  const cfg: McpServerConfig = { type: form.transport }
  if (form.transport === 'stdio') {
    cfg.command = form.command.trim()
    const args = linesToArray(form.argsText)
    if (args.length) cfg.args = args
    const env = textToKeyValue(form.envText)
    if (Object.keys(env).length) cfg.env = env
    if (form.cwd.trim()) cfg.cwd = form.cwd.trim()
  } else {
    cfg.url = form.url.trim()
    const headers = textToKeyValue(form.headersText)
    if (Object.keys(headers).length) cfg.headers = headers
  }
  if (useToolCheckboxes.value) {
    const avail = editingAvailableTools.value
    const checked = avail.filter((t) => toolChecked[t])
    // All ticked collapses to ["*"]; a subset persists the explicit list.
    cfg.enabledTools = checked.length === avail.length ? ['*'] : checked
  } else {
    const tools = linesToArray(form.enabledToolsText)
    if (tools.length) cfg.enabledTools = tools
  }
  if (form.toolTimeout > 0) cfg.toolTimeout = form.toolTimeout
  if (form.includeResources) cfg.includeResources = true
  if (form.includePrompts) cfg.includePrompts = true
  return cfg
}

async function submit() {
  formError.value = null
  const name = form.name.trim()
  if (!name) {
    formError.value = '請輸入 server 名稱'
    return
  }
  if (form.transport === 'stdio' && !form.command.trim()) {
    formError.value = 'stdio 必須填寫 command'
    return
  }
  if (form.transport !== 'stdio' && !form.url.trim()) {
    formError.value = 'HTTP / SSE 必須填寫 url'
    return
  }
  submitting.value = true
  try {
    await mcpStore.upsert(name, buildConfig())
    formOpen.value = false
  } catch (e) {
    formError.value = e instanceof Error ? e.message : '儲存失敗'
  } finally {
    submitting.value = false
  }
}

async function onDelete(name: string) {
  if (!confirm(`確定刪除 MCP server「${name}」？`)) return
  try {
    await mcpStore.remove(name)
  } catch (e) {
    formError.value = e instanceof Error ? e.message : '刪除失敗'
  }
}
</script>

<template>
  <section class="space-y-3">
    <div class="flex items-center justify-between">
      <div>
        <h3 class="text-sm font-medium">MCP Servers</h3>
        <p class="text-xs text-muted-foreground">
          連線：{{ connectedCount }} / {{ configuredCount }} · 變更會寫入 config.json 並即時重連
        </p>
      </div>
      <div class="flex gap-1">
        <Button
          v-if="canEdit"
          variant="outline"
          size="sm"
          class="h-7 px-2 text-xs"
          :disabled="mutating"
          @click="openCreate"
        >
          <Plus class="mr-1 size-3" />
          新增
        </Button>
        <Button
          variant="outline"
          size="sm"
          class="h-7 px-2 text-xs"
          :disabled="!supported || !reloadSupported || reloading || mutating"
          :title="!reloadSupported ? '未設定 config 檔，無法重新載入' : '重新讀取 config 並重連'"
          @click="mcpStore.reload()"
        >
          <RefreshCw class="mr-1 size-3" :class="{ 'animate-spin': reloading }" />
          {{ reloading ? '重新載入中…' : '重新載入' }}
        </Button>
      </div>
    </div>

    <p
      v-if="error"
      class="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive"
    >
      {{ error }}
    </p>

    <!-- Create / edit form -->
    <Collapsible v-model:open="formOpen" class="rounded-md border bg-muted/30">
      <CollapsibleContent class="space-y-3 px-3 py-3">
        <p class="text-xs font-medium text-foreground">
          {{ editingName ? `編輯「${editingName}」` : '新增 MCP server' }}
        </p>

        <div class="space-y-1.5">
          <Label class="text-xs text-muted-foreground" for="mcp-name">名稱</Label>
          <Input
            id="mcp-name"
            v-model="form.name"
            :disabled="editingName !== null"
            placeholder="例如 github、filesystem"
            class="h-8 bg-background text-sm"
          />
        </div>

        <div class="space-y-1.5">
          <Label class="text-xs text-muted-foreground" for="mcp-transport">Transport</Label>
          <select
            id="mcp-transport"
            v-model="form.transport"
            class="h-8 w-full rounded-md border bg-background px-2 text-sm"
          >
            <option value="stdio">stdio（本機 process）</option>
            <option value="streamableHttp">streamableHttp</option>
            <option value="sse">SSE</option>
          </select>
        </div>

        <!-- stdio fields -->
        <template v-if="form.transport === 'stdio'">
          <div class="space-y-1.5">
            <Label class="text-xs text-muted-foreground" for="mcp-command">Command</Label>
            <Input
              id="mcp-command"
              v-model="form.command"
              placeholder="例如 npx"
              class="h-8 bg-background text-sm"
            />
          </div>
          <div class="space-y-1.5">
            <Label class="text-xs text-muted-foreground" for="mcp-args">
              Args（一行一個）
            </Label>
            <Textarea
              id="mcp-args"
              v-model="form.argsText"
              placeholder="-y&#10;@modelcontextprotocol/server-filesystem"
              class="min-h-20 font-mono text-xs"
            />
          </div>
          <div class="space-y-1.5">
            <Label class="text-xs text-muted-foreground" for="mcp-env">
              Env（KEY=VALUE，一行一個）
            </Label>
            <Textarea
              id="mcp-env"
              v-model="form.envText"
              placeholder="API_KEY=${MY_TOKEN}"
              class="min-h-16 font-mono text-xs"
            />
          </div>
          <div class="space-y-1.5">
            <Label class="text-xs text-muted-foreground" for="mcp-cwd">
              工作目錄（cwd，選填）
            </Label>
            <Input
              id="mcp-cwd"
              v-model="form.cwd"
              class="h-8 bg-background text-sm"
            />
          </div>
        </template>

        <!-- http / sse fields -->
        <template v-else>
          <div class="space-y-1.5">
            <Label class="text-xs text-muted-foreground" for="mcp-url">URL</Label>
            <Input
              id="mcp-url"
              v-model="form.url"
              placeholder="https://api.example.com/mcp/"
              class="h-8 bg-background text-sm"
            />
          </div>
          <div class="space-y-1.5">
            <Label class="text-xs text-muted-foreground" for="mcp-headers">
              Headers（KEY=VALUE，一行一個）
            </Label>
            <Textarea
              id="mcp-headers"
              v-model="form.headersText"
              placeholder="Authorization=Bearer ${MY_TOKEN}"
              class="min-h-16 font-mono text-xs"
            />
          </div>
        </template>

        <div class="space-y-1.5">
          <Label class="text-xs text-muted-foreground" for="mcp-timeout">
            Tool Timeout（秒）
          </Label>
          <Input
            id="mcp-timeout"
            v-model.number="form.toolTimeout"
            type="number"
            min="1"
            step="1"
            class="h-8 w-28 bg-background text-sm"
          />
        </div>

        <!-- Tool selection: per-tool checkboxes once connected, else free text -->
        <div class="space-y-1.5">
          <div class="flex items-center justify-between">
            <Label class="text-xs text-muted-foreground">啟用的 Tools</Label>
            <button
              v-if="useToolCheckboxes"
              type="button"
              class="text-[11px] text-muted-foreground hover:text-foreground"
              @click="toggleAllTools(!allToolsChecked)"
            >
              {{ allToolsChecked ? '全部取消' : '全選' }}
            </button>
          </div>

          <div
            v-if="useToolCheckboxes"
            class="max-h-44 space-y-0.5 overflow-y-auto rounded-md border bg-background p-2"
          >
            <label
              v-for="t in editingAvailableTools"
              :key="t"
              class="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 hover:bg-muted/60"
            >
              <input
                v-model="toolChecked[t]"
                type="checkbox"
                class="size-3.5 accent-brand"
              />
              <span class="font-mono text-xs">{{ t }}</span>
            </label>
          </div>

          <template v-else>
            <Textarea
              id="mcp-tools"
              v-model="form.enabledToolsText"
              placeholder="*"
              class="min-h-16 font-mono text-xs"
            />
            <p class="text-[11px] text-muted-foreground">
              一行一個，<code>*</code> 為全部。server 連線後再回來編輯即可逐一勾選。
            </p>
          </template>
        </div>

        <div class="flex items-center justify-between">
          <Label class="text-xs text-muted-foreground">包含 Resources</Label>
          <Switch v-model="form.includeResources" />
        </div>
        <div class="flex items-center justify-between">
          <Label class="text-xs text-muted-foreground">包含 Prompts</Label>
          <Switch v-model="form.includePrompts" />
        </div>

        <p v-if="formError" class="text-xs text-destructive">{{ formError }}</p>
        <div class="flex justify-end gap-1">
          <Button
            variant="ghost"
            size="sm"
            class="h-7 px-2 text-xs"
            @click="formOpen = false"
          >
            取消
          </Button>
          <Button
            size="sm"
            class="h-7 px-3 text-xs"
            :disabled="submitting"
            @click="submit"
          >
            {{ submitting ? '儲存中…' : '儲存並重連' }}
          </Button>
        </div>
      </CollapsibleContent>
    </Collapsible>

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
      尚未設定任何 MCP server，點右上「新增」即可建立。
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
              <template v-if="canEdit">
                <Button
                  variant="ghost"
                  size="icon"
                  class="size-6 text-muted-foreground"
                  title="編輯"
                  :disabled="mutating"
                  @click="openEdit(server.name)"
                >
                  <Pencil class="size-3" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  class="size-6 text-muted-foreground hover:text-destructive"
                  title="刪除"
                  :disabled="mutating"
                  @click="onDelete(server.name)"
                >
                  <Trash2 class="size-3" />
                </Button>
              </template>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

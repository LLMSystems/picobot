<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronDown, ClipboardPaste, RotateCcw, Wrench, X } from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { useSettingsStore } from '@/stores/settings'
import { useCapabilitiesStore } from '@/stores/capabilities'
import {
  toolDisplayName,
  toolDescription,
  toolCategoryLabel,
} from '@/lib/toolDisplay'
import type { ToolCapability } from '@/lib/types'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'update:open', value: boolean): void }>()

const open = computed({
  get: () => props.open,
  set: (v) => emit('update:open', v),
})

const settings = useSettingsStore()
const caps = useCapabilitiesStore()
const {
  systemPrompt,
  temperature,
  maxTokens,
  maxIterations,
  disabledTools,
} = storeToRefs(settings)

const temperatureSliderValue = computed<number[]>({
  get: () => [temperature.value ?? caps.data.default_temperature],
  set: (v) => {
    const n = v[0]
    if (typeof n === 'number') temperature.value = Number(n.toFixed(2))
  },
})

const systemPromptInput = computed<string>({
  get: () => systemPrompt.value ?? '',
  set: (v) => {
    systemPrompt.value = v === '' ? null : v
  },
})

const maxTokensInput = computed<string | number>({
  get: () => (maxTokens.value === null ? '' : maxTokens.value),
  set: (v) => {
    const n = typeof v === 'number' ? v : Number.parseFloat(v)
    maxTokens.value = Number.isFinite(n) && n > 0 ? Math.floor(n) : null
  },
})

const maxIterationsInput = computed<string | number>({
  get: () => (maxIterations.value === null ? '' : maxIterations.value),
  set: (v) => {
    const n = typeof v === 'number' ? v : Number.parseFloat(v)
    maxIterations.value = Number.isFinite(n) && n > 0 ? Math.floor(n) : null
  },
})

const systemPromptOpen = ref(false)

function resetSystemPrompt() {
  systemPrompt.value = null
}

function loadDefaultIntoPrompt() {
  systemPrompt.value = caps.data.default_system_prompt
}
function resetTemperature() {
  temperature.value = null
}
function resetMaxTokens() {
  maxTokens.value = null
}
function resetMaxIterations() {
  maxIterations.value = null
}

const toolsByCategory = computed(() => {
  const map = new Map<string, ToolCapability[]>()
  for (const t of caps.data.tools) {
    const list = map.get(t.category) ?? []
    list.push(t)
    map.set(t.category, list)
  }
  return [...map.entries()].sort(([a], [b]) => a.localeCompare(b))
})

const enabledToolCount = computed(
  () => caps.data.tools.length - disabledTools.value.length,
)

function isToolEnabled(name: string): boolean {
  return settings.isToolEnabled(name)
}

function setToolEnabled(name: string, enabled: boolean) {
  settings.setToolEnabled(name, enabled)
}

function enableAllTools() {
  disabledTools.value = []
}

function disableAllTools() {
  disabledTools.value = caps.data.tools.map((t) => t.name)
}

function resetAll() {
  settings.resetAll()
}

function toolLabel(tool: { name: string }): string {
  return toolDisplayName(tool.name, caps.toolMap.get(tool.name))
}
function toolDescLabel(tool: { name: string; description?: string }): string {
  return toolDescription(tool.name, caps.toolMap.get(tool.name))
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent
      class="flex max-h-[85vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-2xl"
    >
      <DialogHeader class="border-b px-6 py-4">
        <DialogTitle>設定</DialogTitle>
        <DialogDescription>
          設定僅儲存在這個瀏覽器；空白欄位代表使用後端預設值。
        </DialogDescription>
      </DialogHeader>

      <div class="flex-1 overflow-y-auto px-6 py-5 space-y-6">
        <!-- System Prompt -->
        <Collapsible
          v-model:open="systemPromptOpen"
          class="rounded-md border bg-muted/30"
        >
          <CollapsibleTrigger
            class="group flex w-full items-center gap-2 px-3 py-2 text-left"
          >
            <ChevronDown
              class="size-4 text-muted-foreground transition-transform group-data-[state=closed]:-rotate-90"
            />
            <Label class="cursor-pointer text-sm font-medium">
              System Prompt
            </Label>
            <span
              v-if="systemPrompt !== null"
              class="inline-block size-1.5 rounded-full bg-foreground/60"
              aria-label="已自訂"
              :title="`已自訂 · ${systemPrompt.length} 字元`"
            />
            <span class="ml-auto text-xs text-muted-foreground">
              {{
                systemPrompt !== null
                  ? `已自訂 · ${systemPrompt.length} 字元`
                  : `預設 · ${caps.data.default_system_prompt.length} 字元`
              }}
            </span>
          </CollapsibleTrigger>

          <CollapsibleContent class="space-y-2 border-t bg-background px-3 py-3">
            <div class="flex items-center gap-1">
              <Button
                v-if="systemPrompt === null && caps.data.default_system_prompt"
                variant="outline"
                size="sm"
                class="h-7 px-2 text-xs"
                @click="loadDefaultIntoPrompt"
              >
                <ClipboardPaste class="mr-1 size-3" />
                載入預設來微調
              </Button>
              <Button
                v-if="systemPrompt !== null"
                variant="ghost"
                size="sm"
                class="h-7 px-2 text-xs text-muted-foreground"
                @click="resetSystemPrompt"
              >
                <RotateCcw class="mr-1 size-3" />
                還原預設
              </Button>
            </div>
            <Textarea
              v-model="systemPromptInput"
              :placeholder="caps.data.default_system_prompt || '輸入要覆蓋的 system prompt…'"
              class="min-h-48 font-mono text-xs"
            />
            <p class="text-xs text-muted-foreground">
              {{
                systemPrompt === null
                  ? '留空代表使用後端預設值；點擊上方「載入預設來微調」即可在預設值基礎上修改。'
                  : '此內容將覆蓋後端預設值。'
              }}
            </p>
          </CollapsibleContent>
        </Collapsible>

        <!-- Model Parameters -->
        <section class="space-y-3 rounded-md border bg-muted/30 px-3 py-3">
          <h3 class="text-sm font-medium">Model 參數</h3>

          <!-- temperature -->
          <div class="space-y-1.5">
            <div class="flex items-center justify-between">
              <Label class="text-xs text-muted-foreground">Temperature</Label>
              <div class="flex items-center gap-1.5">
                <span class="font-mono text-xs tabular-nums">
                  {{ (temperature ?? caps.data.default_temperature).toFixed(2) }}
                </span>
                <span
                  v-if="temperature === null"
                  class="text-[10px] text-muted-foreground"
                >
                  · 預設
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  class="size-5"
                  :disabled="temperature === null"
                  title="還原預設"
                  @click="resetTemperature"
                >
                  <X class="size-3" />
                </Button>
              </div>
            </div>
            <Slider
              v-model="temperatureSliderValue"
              :min="0"
              :max="2"
              :step="0.05"
            />
          </div>

          <!-- max_tokens -->
          <div class="space-y-1.5">
            <div class="flex items-center justify-between">
              <Label class="text-xs text-muted-foreground" for="settings-max-tokens">
                Max Tokens
              </Label>
              <div class="flex items-center gap-1.5">
                <span
                  v-if="maxTokens === null"
                  class="text-[10px] text-muted-foreground"
                >
                  預設 {{ caps.data.default_max_tokens ?? '—' }}
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  class="size-5"
                  :disabled="maxTokens === null"
                  title="還原預設"
                  @click="resetMaxTokens"
                >
                  <X class="size-3" />
                </Button>
              </div>
            </div>
            <Input
              id="settings-max-tokens"
              v-model="maxTokensInput"
              type="number"
              min="1"
              step="1"
              :placeholder="caps.data.default_max_tokens?.toString() ?? '不限制'"
              class="h-8 bg-background text-sm"
            />
          </div>

          <!-- max_iterations -->
          <div class="space-y-1.5">
            <div class="flex items-center justify-between">
              <Label class="text-xs text-muted-foreground" for="settings-max-iter">
                Max Iterations
              </Label>
              <div class="flex items-center gap-1.5">
                <span
                  v-if="maxIterations === null"
                  class="text-[10px] text-muted-foreground"
                >
                  預設 {{ caps.data.max_iterations }}
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  class="size-5"
                  :disabled="maxIterations === null"
                  title="還原預設"
                  @click="resetMaxIterations"
                >
                  <X class="size-3" />
                </Button>
              </div>
            </div>
            <Input
              id="settings-max-iter"
              v-model="maxIterationsInput"
              type="number"
              min="1"
              step="1"
              :placeholder="caps.data.max_iterations.toString()"
              class="h-8 bg-background text-sm"
            />
          </div>
        </section>

        <!-- Tools -->
        <section class="space-y-3">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="text-sm font-medium">Tools</h3>
              <p class="text-xs text-muted-foreground">
                啟用：{{ enabledToolCount }} / {{ caps.data.tools.length }}
              </p>
            </div>
            <div class="flex gap-1">
              <Button
                variant="ghost"
                size="sm"
                class="h-7 px-2 text-xs text-muted-foreground"
                :disabled="disabledTools.length === 0"
                @click="enableAllTools"
              >
                全部啟用
              </Button>
              <Button
                variant="ghost"
                size="sm"
                class="h-7 px-2 text-xs text-muted-foreground"
                :disabled="disabledTools.length === caps.data.tools.length"
                @click="disableAllTools"
              >
                全部停用
              </Button>
            </div>
          </div>

          <div
            v-if="caps.data.tools.length === 0"
            class="rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground"
          >
            目前沒有可用的 tools。
          </div>

          <div v-else class="space-y-3">
            <div
              v-for="[cat, tools] in toolsByCategory"
              :key="cat"
              class="overflow-hidden rounded-md border bg-muted/30"
            >
              <div
                class="border-b bg-muted/40 px-3 py-1.5 text-xs font-medium text-muted-foreground"
              >
                {{ toolCategoryLabel(cat) }}
              </div>
              <div class="divide-y">
                <div
                  v-for="tool in tools"
                  :key="tool.name"
                  class="flex items-start justify-between gap-3 bg-background px-3 py-2"
                >
                  <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-1.5">
                      <Wrench class="size-3 text-muted-foreground" />
                      <span class="text-xs font-medium">
                        {{ toolLabel(tool) }}
                      </span>
                      <code
                        v-if="toolLabel(tool) !== tool.name"
                        class="font-mono text-[10px] text-muted-foreground/70"
                      >
                        {{ tool.name }}
                      </code>
                      <span
                        v-if="tool.dangerous"
                        class="rounded border border-amber-500/40 bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-700 dark:text-amber-400"
                        title="可能修改檔案或執行指令"
                      >
                        高權限
                      </span>
                    </div>
                    <p
                      v-if="toolDescLabel(tool)"
                      class="mt-0.5 line-clamp-2 text-xs text-muted-foreground"
                    >
                      {{ toolDescLabel(tool) }}
                    </p>
                  </div>
                  <Switch
                    :model-value="isToolEnabled(tool.name)"
                    @update:model-value="(v) => setToolEnabled(tool.name, v)"
                  />
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>

      <div class="flex items-center justify-between border-t px-6 py-3">
        <Button
          variant="ghost"
          size="sm"
          :disabled="!settings.hasOverrides"
          @click="resetAll"
        >
          <RotateCcw class="mr-1 size-3" />
          全部還原預設
        </Button>
        <Button
          size="sm"
          class="bg-brand text-brand-foreground hover:bg-brand/90"
          @click="open = false"
        >
          完成
        </Button>
      </div>
    </DialogContent>
  </Dialog>
</template>

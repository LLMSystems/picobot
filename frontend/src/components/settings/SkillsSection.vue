<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { Plus, Sparkles, Trash2, Upload } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { useSkillsStore } from '@/stores/skills'

const skillsStore = useSkillsStore()
const { skills, loading, error, enabledCount } = storeToRefs(skillsStore)

const createOpen = ref(false)
const newName = ref('')
const newContent = ref('')
const submitting = ref(false)
const submitError = ref<string | null>(null)

const folderInput = ref<HTMLInputElement | null>(null)
const importing = ref(false)
const importError = ref<string | null>(null)

const DEFAULT_TEMPLATE = `---
name: my-skill
description: 簡短描述這個 skill 何時該被使用
---

# My Skill

在這裡寫下 agent 該如何使用這個 skill 的說明。
`

onMounted(() => {
  void skillsStore.load()
})

function toggle(name: string, enabled: boolean) {
  void skillsStore.setDisabled(name, !enabled)
}

async function remove(name: string) {
  if (!confirm(`確定刪除自訂 skill「${name}」？`)) return
  try {
    await skillsStore.remove(name)
  } catch (e) {
    submitError.value = e instanceof Error ? e.message : '刪除失敗'
  }
}

function loadTemplate() {
  if (!newContent.value.trim()) newContent.value = DEFAULT_TEMPLATE
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = String(reader.result)
      const comma = result.indexOf(',')
      resolve(comma >= 0 ? result.slice(comma + 1) : result)
    }
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

function relPath(file: File): string {
  return (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
}

function triggerImport() {
  importError.value = null
  folderInput.value?.click()
}

async function onFolderPicked(event: Event) {
  const input = event.target as HTMLInputElement
  const picked = input.files ? Array.from(input.files) : []
  const first = picked[0]
  if (!first) return
  importError.value = null
  importing.value = true
  try {
    const folderName = relPath(first).split('/')[0] ?? ''
    const skillMd = picked.find((f) => relPath(f) === `${folderName}/SKILL.md`)
    if (!folderName || !skillMd) {
      importError.value = '請選擇含有 SKILL.md 的 skill 資料夾'
      return
    }
    const content = await skillMd.text()
    const extras = picked.filter((f) => {
      const base = relPath(f).split('/').pop() ?? ''
      return f !== skillMd && !base.startsWith('.')
    })
    const files = await Promise.all(
      extras.map(async (f) => ({
        path: relPath(f).slice(folderName.length + 1),
        content_base64: await fileToBase64(f),
      })),
    )
    await skillsStore.create(folderName, content, files)
  } catch (e) {
    importError.value = e instanceof Error ? e.message : '匯入失敗'
  } finally {
    importing.value = false
    input.value = ''
  }
}

async function submit() {
  submitError.value = null
  const name = newName.value.trim()
  if (!name) {
    submitError.value = '請輸入 skill 名稱'
    return
  }
  if (!newContent.value.trim()) {
    submitError.value = '請輸入 SKILL.md 內容'
    return
  }
  submitting.value = true
  try {
    await skillsStore.create(name, newContent.value)
    newName.value = ''
    newContent.value = ''
    createOpen.value = false
  } catch (e) {
    submitError.value = e instanceof Error ? e.message : '建立失敗'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="space-y-3">
    <div class="flex items-center justify-between">
      <div>
        <h3 class="text-sm font-medium">Skills</h3>
        <p class="text-xs text-muted-foreground">
          啟用：{{ enabledCount }} / {{ skills.length }} · 變更會套用到之後新開的對話
        </p>
      </div>
      <div class="flex gap-1">
        <Button
          variant="outline"
          size="sm"
          class="h-7 px-2 text-xs"
          :disabled="importing"
          @click="triggerImport"
        >
          <Upload class="mr-1 size-3" />
          {{ importing ? '匯入中…' : '匯入資料夾' }}
        </Button>
        <Button
          variant="outline"
          size="sm"
          class="h-7 px-2 text-xs"
          @click="createOpen = !createOpen"
        >
          <Plus class="mr-1 size-3" />
          手動新增
        </Button>
      </div>
      <input
        ref="folderInput"
        type="file"
        webkitdirectory
        directory
        multiple
        class="hidden"
        @change="onFolderPicked"
      />
    </div>

    <p
      v-if="importError"
      class="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive"
    >
      {{ importError }}
    </p>

    <p
      v-if="error"
      class="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive"
    >
      {{ error }}
    </p>

    <!-- Create form -->
    <Collapsible v-model:open="createOpen" class="rounded-md border bg-muted/30">
      <CollapsibleContent class="space-y-2 px-3 py-3">
        <div class="rounded-md border border-border bg-background px-3 py-2 text-[11px] text-muted-foreground">
          <p class="mb-1 font-medium text-foreground">SKILL.md 格式規則</p>
          <ul class="list-disc space-y-0.5 pl-4">
            <li>必須以 <code>---</code> 包住的 YAML frontmatter 開頭</li>
            <li>frontmatter 必須有非空的 <code>description</code>（告訴 agent 何時使用）</li>
            <li>若有寫 <code>name</code>，需與資料夾／名稱一致</li>
          </ul>
        </div>
        <div class="space-y-1.5">
          <Label class="text-xs text-muted-foreground" for="skill-name">名稱</Label>
          <Input
            id="skill-name"
            v-model="newName"
            placeholder="例如 my-skill（只能用英數字、- 與 _）"
            class="h-8 bg-background text-sm"
          />
        </div>
        <div class="space-y-1.5">
          <div class="flex items-center justify-between">
            <Label class="text-xs text-muted-foreground" for="skill-content">
              SKILL.md 內容
            </Label>
            <Button
              variant="ghost"
              size="sm"
              class="h-6 px-2 text-[10px] text-muted-foreground"
              @click="loadTemplate"
            >
              載入範本
            </Button>
          </div>
          <Textarea
            id="skill-content"
            v-model="newContent"
            placeholder="貼上含 frontmatter 的 SKILL.md 內容…"
            class="min-h-40 font-mono text-xs"
          />
        </div>
        <p v-if="submitError" class="text-xs text-destructive">{{ submitError }}</p>
        <div class="flex justify-end gap-1">
          <Button variant="ghost" size="sm" class="h-7 px-2 text-xs" @click="createOpen = false">
            取消
          </Button>
          <Button size="sm" class="h-7 px-3 text-xs" :disabled="submitting" @click="submit">
            {{ submitting ? '建立中…' : '建立' }}
          </Button>
        </div>
      </CollapsibleContent>
    </Collapsible>

    <div
      v-if="loading && skills.length === 0"
      class="rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground"
    >
      載入中…
    </div>
    <div
      v-else-if="skills.length === 0"
      class="rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground"
    >
      目前沒有可用的 skills。
    </div>

    <div v-else class="overflow-hidden rounded-md border bg-muted/30">
      <div class="divide-y">
        <div
          v-for="skill in skills"
          :key="skill.name"
          class="flex items-start justify-between gap-3 bg-background px-3 py-2"
        >
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-1.5">
              <Sparkles class="size-3 text-muted-foreground" />
              <span class="text-xs font-medium">{{ skill.name }}</span>
              <span
                v-if="skill.source === 'builtin'"
                class="rounded border border-border bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
              >
                內建
              </span>
              <span
                v-else
                class="rounded border border-brand/40 bg-brand/10 px-1.5 py-0.5 text-[10px] text-brand"
              >
                自訂
              </span>
              <span
                v-if="skill.always"
                class="rounded border border-border bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
                title="預設一律啟用並注入 prompt"
              >
                always
              </span>
            </div>
            <p
              v-if="skill.description"
              class="mt-0.5 line-clamp-2 text-xs text-muted-foreground"
            >
              {{ skill.description }}
            </p>
          </div>
          <div class="flex items-center gap-1.5">
            <Button
              v-if="skill.source === 'custom'"
              variant="ghost"
              size="icon"
              class="size-6 text-muted-foreground hover:text-destructive"
              title="刪除"
              @click="remove(skill.name)"
            >
              <Trash2 class="size-3" />
            </Button>
            <Switch
              :model-value="!skill.disabled"
              @update:model-value="(v: boolean) => toggle(skill.name, v)"
            />
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ChevronRight, File, Folder, FolderOpen, Loader2 } from 'lucide-vue-next'
import { useWorkspaceStore } from '@/stores/workspace'
import { useRelativeTime } from '@/composables/useRelativeTime'
import type { WorkspaceEntryDTO } from '@/lib/types'

const props = defineProps<{
  entry: WorkspaceEntryDTO
  depth: number
}>()

const ws = useWorkspaceStore()

const isDir = computed(() => props.entry.type === 'directory')
const isExpanded = computed(() => ws.expanded.has(props.entry.path))
const isSelected = computed(() => ws.selectedPath === props.entry.path)
const dirState = computed(() => ws.getDir(props.entry.path))
const children = computed(() =>
  isDir.value && isExpanded.value ? ws.childrenOf(props.entry.path) : [],
)

const { text: relative } = useRelativeTime(() => props.entry.updated_at)

function onClick() {
  if (isDir.value) {
    void ws.toggleExpand(props.entry.path)
  } else {
    void ws.select(props.entry.path)
  }
}

const indentStyle = computed(() => ({
  paddingLeft: `${props.depth * 12 + 6}px`,
}))
</script>

<template>
  <div>
    <button
      type="button"
      class="group flex w-full items-center gap-1 rounded px-1.5 py-1 text-left text-xs transition-colors"
      :class="
        isSelected
          ? 'bg-accent text-accent-foreground'
          : 'hover:bg-accent/60'
      "
      :style="indentStyle"
      @click="onClick"
    >
      <ChevronRight
        v-if="isDir"
        class="size-3 shrink-0 transition-transform"
        :class="isExpanded ? 'rotate-90' : ''"
      />
      <span v-else class="size-3 shrink-0" />

      <Loader2
        v-if="isDir && dirState.loading"
        class="size-3.5 shrink-0 animate-spin text-muted-foreground"
      />
      <FolderOpen
        v-else-if="isDir && isExpanded"
        class="size-3.5 shrink-0 text-amber-500"
      />
      <Folder
        v-else-if="isDir"
        class="size-3.5 shrink-0 text-amber-500"
      />
      <File v-else class="size-3.5 shrink-0 text-muted-foreground" />

      <span class="flex-1 truncate font-mono">{{ entry.name }}</span>
      <span
        class="hidden shrink-0 text-[10px] text-muted-foreground group-hover:inline"
        :title="entry.updated_at"
      >
        {{ relative }}
      </span>
    </button>

    <template v-if="isDir && isExpanded">
      <WorkspaceTreeNode
        v-for="child in children"
        :key="child.path"
        :entry="child"
        :depth="depth + 1"
      />
      <p
        v-if="dirState.truncated"
        class="ml-6 text-[10px] italic text-muted-foreground"
      >
        … 已截斷，可能還有檔案
      </p>
    </template>
  </div>
</template>

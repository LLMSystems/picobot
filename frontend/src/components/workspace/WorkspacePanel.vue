<script setup lang="ts">
import { computed } from 'vue'
import WorkspaceHeader from './WorkspaceHeader.vue'
import WorkspaceTree from './WorkspaceTree.vue'
import WorkspaceFilePreview from './WorkspaceFilePreview.vue'
import { useVerticalSplit } from '@/composables/useVerticalSplit'

const { containerRef, ratio, onPointerDown } = useVerticalSplit({
  storageKey: 'picobot:workspace:split',
  initial: 0.45,
  min: 0.15,
  max: 0.85,
})

const treeStyle = computed(() => ({ flex: `${ratio.value} 1 0` }))
const previewStyle = computed(() => ({ flex: `${1 - ratio.value} 1 0` }))
</script>

<template>
  <aside
    class="flex h-full w-80 shrink-0 flex-col border-l bg-background"
  >
    <WorkspaceHeader />
    <div ref="containerRef" class="flex min-h-0 flex-1 flex-col">
      <WorkspaceTree
        class="min-h-0 overflow-hidden"
        :style="treeStyle"
      />
      <div
        class="group relative h-1.5 shrink-0 cursor-row-resize bg-border transition-colors hover:bg-primary/40"
        role="separator"
        aria-orientation="horizontal"
        aria-label="拖曳調整上下比例"
        @pointerdown="onPointerDown"
      >
        <span
          class="pointer-events-none absolute inset-x-0 top-1/2 -translate-y-1/2 mx-auto block h-0.5 w-8 rounded-full bg-foreground/20 transition-colors group-hover:bg-foreground/50"
        />
      </div>
      <WorkspaceFilePreview
        class="min-h-0 overflow-hidden"
        :style="previewStyle"
      />
    </div>
  </aside>
</template>

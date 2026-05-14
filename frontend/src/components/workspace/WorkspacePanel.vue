<script setup lang="ts">
import WorkspaceHeader from './WorkspaceHeader.vue'
import WorkspaceTree from './WorkspaceTree.vue'
import WorkspaceFilePreview from './WorkspaceFilePreview.vue'
</script>

<template>
  <aside
    class="flex h-full w-80 shrink-0 flex-col border-l bg-background"
  >
    <WorkspaceHeader />
    <div class="grid min-h-0 flex-1 grid-rows-[1fr_1fr]">
      <WorkspaceTree class="min-h-0" />
      <WorkspaceFilePreview class="min-h-0" />
    </div>
  </aside>
</template>

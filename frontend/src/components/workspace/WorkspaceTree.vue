<script setup lang="ts">
import { useWorkspaceStore } from '@/stores/workspace'
import WorkspaceTreeNode from './WorkspaceTreeNode.vue'
import WorkspaceEmpty from './WorkspaceEmpty.vue'
import { Skeleton } from '@/components/ui/skeleton'

const ws = useWorkspaceStore()
</script>

<template>
  <div class="flex h-full flex-col overflow-hidden">
    <template v-if="ws.loadState === 'loading' && !ws.hasContent">
      <div class="space-y-2 p-3">
        <Skeleton v-for="i in 4" :key="i" class="h-5 w-full" />
      </div>
    </template>
    <template v-else-if="ws.loadState === 'unavailable'">
      <WorkspaceEmpty variant="unavailable" />
    </template>
    <template v-else-if="ws.loadState === 'error'">
      <WorkspaceEmpty variant="error" />
    </template>
    <template v-else-if="ws.loadState === 'empty'">
      <WorkspaceEmpty variant="empty" />
    </template>
    <template v-else>
      <div class="flex-1 overflow-y-auto px-1 py-2">
        <WorkspaceTreeNode
          v-for="entry in ws.rootChildren"
          :key="entry.path"
          :entry="entry"
          :depth="0"
        />
      </div>
    </template>
  </div>
</template>

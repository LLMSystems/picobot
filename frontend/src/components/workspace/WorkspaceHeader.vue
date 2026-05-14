<script setup lang="ts">
import { Button } from '@/components/ui/button'
import { RefreshCw, X, ArrowDownAZ, Clock } from 'lucide-vue-next'
import { useWorkspaceStore } from '@/stores/workspace'

const ws = useWorkspaceStore()
</script>

<template>
  <header
    class="flex h-12 shrink-0 items-center gap-2 border-b bg-background px-3"
  >
    <span class="text-sm font-medium">Workspace</span>
    <div class="ml-auto flex items-center gap-1">
      <Button
        v-if="ws.sortMode === 'updated'"
        variant="ghost"
        size="icon"
        class="size-7"
        aria-label="改用名稱排序"
        title="目前：依修改時間"
        @click="ws.setSortMode('name')"
      >
        <Clock class="size-4" />
      </Button>
      <Button
        v-else
        variant="ghost"
        size="icon"
        class="size-7"
        aria-label="改用修改時間排序"
        title="目前：依名稱"
        @click="ws.setSortMode('updated')"
      >
        <ArrowDownAZ class="size-4" />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        class="size-7"
        aria-label="重新整理"
        title="重新整理"
        @click="ws.refreshExpanded()"
      >
        <RefreshCw class="size-4" />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        class="size-7"
        aria-label="關閉 workspace"
        title="關閉"
        @click="ws.setVisible(false)"
      >
        <X class="size-4" />
      </Button>
    </div>
  </header>
</template>

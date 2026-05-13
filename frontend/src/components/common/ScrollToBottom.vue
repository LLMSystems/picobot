<script setup lang="ts">
import { Button } from '@/components/ui/button'
import { ArrowDown } from 'lucide-vue-next'
</script>

<template>
  <Button
    variant="secondary"
    size="sm"
    class="gap-1 rounded-full shadow"
    aria-label="跳到最新訊息"
  >
    <ArrowDown class="size-4" />
    新訊息
  </Button>
</template>

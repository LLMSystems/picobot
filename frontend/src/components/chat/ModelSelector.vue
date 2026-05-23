<script setup lang="ts">
import { computed } from 'vue'
import { ChevronDown, Check } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useSelectedModel } from '@/composables/useSelectedModel'

const {
  selected,
  enabled,
  defaultModel,
  availableModels,
  isDefault,
  setSelected,
  resetToDefault,
} = useSelectedModel()

const buttonLabel = computed(() =>
  isDefault.value ? defaultModel.value : (selected.value ?? defaultModel.value),
)
</script>

<template>
  <DropdownMenu v-if="enabled">
    <DropdownMenuTrigger as-child>
      <Button
        variant="ghost"
        size="sm"
        class="h-8 gap-1 rounded-full px-2.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
        aria-label="選擇模型"
      >
        <span class="max-w-[140px] truncate">{{ buttonLabel }}</span>
        <ChevronDown class="size-3.5 opacity-70" />
      </Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="start" class="w-56">
      <DropdownMenuLabel class="text-xs text-muted-foreground">
        選擇模型
      </DropdownMenuLabel>
      <DropdownMenuSeparator />
      <DropdownMenuItem
        class="flex items-center justify-between gap-2"
        @click="resetToDefault"
      >
        <div class="flex flex-col">
          <span class="text-sm">預設 ({{ defaultModel }})</span>
          <span class="text-[10px] text-muted-foreground">
            Server default
          </span>
        </div>
        <Check v-if="isDefault" class="size-4 text-foreground" />
      </DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem
        v-for="m in availableModels"
        :key="m"
        class="flex items-center justify-between gap-2"
        @click="setSelected(m)"
      >
        <span class="text-sm">{{ m }}</span>
        <Check
          v-if="!isDefault && selected === m"
          class="size-4 text-foreground"
        />
      </DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import ConnectionBanner from '@/components/common/ConnectionBanner.vue'
import ModeSwitcher from '@/components/layout/ModeSwitcher.vue'
import AlertsBadge from '@/components/layout/AlertsBadge.vue'
import DashboardAnchorRail from '@/components/dashboard/DashboardAnchorRail.vue'
import { Button } from '@/components/ui/button'
import { Moon, Sun } from 'lucide-vue-next'
import { useTheme } from '@/composables/useTheme'
import picoagentLogo from '@/assets/picoagent_icon.png'

const { theme, toggle: toggleTheme } = useTheme()

// Reference to the scrollable main content — passed to AnchorRail so its
// IntersectionObserver can use this element as the observation root.
const scrollRoot = ref<HTMLElement | null>(null)
</script>

<template>
  <div class="flex h-screen w-screen flex-col bg-background text-foreground">
    <ConnectionBanner />
    <header class="flex h-12 shrink-0 items-center gap-3 border-b bg-background px-4">
      <div class="flex items-center gap-2">
        <img
          :src="picoagentLogo"
          alt=""
          aria-hidden="true"
          class="size-7 select-none object-contain"
          draggable="false"
        />
        <span class="text-sm font-semibold tracking-tight">Picobot</span>
      </div>
      <div class="ml-2">
        <ModeSwitcher />
      </div>
      <div class="flex-1" />
      <AlertsBadge />
      <Button
        variant="ghost"
        size="icon"
        aria-label="切換主題"
        @click="toggleTheme"
      >
        <Sun v-if="theme === 'dark'" class="size-4" />
        <Moon v-else class="size-4" />
      </Button>
    </header>
    <div class="relative flex min-h-0 flex-1 overflow-hidden">
      <DashboardAnchorRail :scroll-container="scrollRoot" />
      <main ref="scrollRoot" class="flex-1 overflow-y-auto">
        <slot />
      </main>
    </div>
  </div>
</template>

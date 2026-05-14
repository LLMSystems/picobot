<script setup lang="ts">
import { computed, ref } from 'vue'
import Sidebar from './Sidebar.vue'
import TopBar from './TopBar.vue'
import ConnectionBanner from '@/components/common/ConnectionBanner.vue'
import WorkspacePanel from '@/components/workspace/WorkspacePanel.vue'
import { useCapabilitiesStore } from '@/stores/capabilities'
import { useWorkspaceStore } from '@/stores/workspace'
import { useHorizontalResize } from '@/composables/useHorizontalResize'

const caps = useCapabilitiesStore()
const ws = useWorkspaceStore()

const sidebarOpenMobile = ref(false)
function toggleSidebar() {
  sidebarOpenMobile.value = !sidebarOpenMobile.value
}
function closeSidebar() {
  sidebarOpenMobile.value = false
}

const workspaceVisible = computed(
  () => caps.data.features.session_workspace && ws.visible,
)

const {
  targetRef: sidebarRef,
  width: sidebarWidth,
  onPointerDown: onSidebarResize,
} = useHorizontalResize({
  storageKey: 'picobot:sidebar:width',
  initial: 288,
  min: 220,
  max: 480,
  edge: 'right',
})

const sidebarStyle = computed(() => ({ width: `${sidebarWidth.value}px` }))
</script>

<template>
  <div class="flex h-screen w-screen flex-col bg-background text-foreground">
    <ConnectionBanner />
    <div class="relative flex flex-1 min-h-0 overflow-hidden">
      <aside
        ref="sidebarRef"
        class="absolute inset-y-0 left-0 z-30 shrink-0 border-r bg-sidebar text-sidebar-foreground transition-transform md:static md:translate-x-0"
        :class="sidebarOpenMobile ? 'translate-x-0' : '-translate-x-full'"
        :style="sidebarStyle"
      >
        <Sidebar @select="closeSidebar" />
        <div
          class="group absolute inset-y-0 -right-1 z-10 hidden w-2 cursor-col-resize md:block"
          role="separator"
          aria-orientation="vertical"
          aria-label="拖曳調整 sidebar 寬度"
          @pointerdown="onSidebarResize"
        >
          <span
            class="pointer-events-none absolute inset-y-0 left-1/2 -translate-x-1/2 w-px bg-transparent transition-colors group-hover:bg-primary/40"
          />
        </div>
      </aside>
      <div
        v-if="sidebarOpenMobile"
        class="absolute inset-0 z-20 bg-black/40 md:hidden"
        @click="closeSidebar"
      />
      <div class="flex min-w-0 flex-1 flex-col">
        <TopBar @toggle-sidebar="toggleSidebar" />
        <main class="relative flex flex-1 min-h-0 overflow-hidden">
          <div class="flex min-w-0 flex-1 flex-col">
            <slot />
          </div>
          <WorkspacePanel v-if="workspaceVisible" class="hidden lg:flex" />
        </main>
      </div>
    </div>
  </div>
</template>

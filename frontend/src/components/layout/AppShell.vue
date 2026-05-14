<script setup lang="ts">
import { computed, ref } from 'vue'
import Sidebar from './Sidebar.vue'
import TopBar from './TopBar.vue'
import ConnectionBanner from '@/components/common/ConnectionBanner.vue'
import WorkspacePanel from '@/components/workspace/WorkspacePanel.vue'
import { useCapabilitiesStore } from '@/stores/capabilities'
import { useWorkspaceStore } from '@/stores/workspace'

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
</script>

<template>
  <div class="flex h-screen w-screen flex-col bg-background text-foreground">
    <ConnectionBanner />
    <div class="relative flex flex-1 min-h-0 overflow-hidden">
      <aside
        class="absolute inset-y-0 left-0 z-30 w-72 shrink-0 border-r bg-sidebar text-sidebar-foreground transition-transform md:static md:translate-x-0"
        :class="sidebarOpenMobile ? 'translate-x-0' : '-translate-x-full'"
      >
        <Sidebar @select="closeSidebar" />
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

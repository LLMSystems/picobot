<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Settings,
  Moon,
  Sun,
  Bell,
  BellOff,
  LogOut,
  ChevronsUpDown,
} from 'lucide-vue-next'
import SettingsDialog from '@/components/settings/SettingsDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { useSettingsStore } from '@/stores/settings'
import { useTheme } from '@/composables/useTheme'
import { useNotifications } from '@/composables/useNotifications'
import { toast } from 'vue-sonner'

const auth = useAuthStore()
const settings = useSettingsStore()
const { theme, toggle: toggleTheme } = useTheme()
const notifs = useNotifications()
const router = useRouter()

const settingsOpen = ref(false)

const username = computed(() => auth.user?.username ?? '')
const initials = computed(() => username.value.slice(0, 2).toUpperCase() || '?')

const notificationsOn = computed(
  () => notifs.enabled.value && notifs.permission.value === 'granted',
)

async function handleLogout() {
  await auth.logout()
  await router.replace({ name: 'login' })
}

async function toggleNotifications() {
  if (!notifs.supported) {
    toast.error('此瀏覽器不支援通知')
    return
  }
  const result = await notifs.toggle()
  if (notifs.permission.value === 'denied') {
    toast.error('通知權限已被瀏覽器拒絕', {
      description: '請在瀏覽器設定開啟此網站的通知權限',
    })
    return
  }
  toast[result ? 'success' : 'info'](result ? '已開啟通知' : '已關閉通知', {
    description: result ? '長任務完成時若分頁不在前景會通知你' : undefined,
  })
}
</script>

<template>
  <div v-if="auth.isAuthenticated" class="border-t p-2">
    <DropdownMenu>
      <DropdownMenuTrigger as-child>
        <button
          class="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition hover:bg-muted"
          aria-label="帳號選單"
        >
          <Avatar class="size-7 shrink-0">
            <AvatarFallback class="bg-brand-soft text-xs font-medium text-brand-strong">
              {{ initials }}
            </AvatarFallback>
          </Avatar>
          <span class="min-w-0 flex-1 truncate text-sm font-medium">
            {{ username }}
          </span>
          <span class="relative shrink-0 text-muted-foreground">
            <ChevronsUpDown class="size-4" />
            <span
              v-if="settings.hasOverrides"
              class="absolute -right-0.5 -top-0.5 size-1.5 rounded-full bg-amber-500"
              aria-hidden="true"
            />
          </span>
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent side="top" align="start" class="w-[var(--reka-dropdown-menu-trigger-width)] min-w-56">
        <DropdownMenuItem @click="settingsOpen = true">
          <Settings class="size-4" />
          <span class="flex-1">設定</span>
          <span
            v-if="settings.hasOverrides"
            class="size-1.5 rounded-full bg-amber-500"
            aria-hidden="true"
          />
        </DropdownMenuItem>

        <DropdownMenuItem @click="toggleTheme">
          <Sun v-if="theme === 'dark'" class="size-4" />
          <Moon v-else class="size-4" />
          <span>{{ theme === 'dark' ? '切換為淺色' : '切換為深色' }}</span>
        </DropdownMenuItem>

        <DropdownMenuItem v-if="notifs.supported" @click="toggleNotifications">
          <Bell v-if="notificationsOn" class="size-4" />
          <BellOff v-else class="size-4" />
          <span>{{ notificationsOn ? '關閉通知' : '開啟通知' }}</span>
        </DropdownMenuItem>

        <DropdownMenuSeparator />

        <DropdownMenuItem
          class="text-destructive focus:text-destructive"
          @click="handleLogout"
        >
          <LogOut class="size-4" />
          <span>登出</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>

    <SettingsDialog v-model:open="settingsOpen" />
  </div>
</template>

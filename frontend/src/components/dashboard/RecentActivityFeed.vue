<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { MessageSquare, Activity, ArrowRight } from 'lucide-vue-next'
import { useSessionsStore } from '@/stores/sessions'
import { relativeTime, truncate } from '@/lib/format'

const props = defineProps<{ limit?: number }>()

const sessions = useSessionsStore()
const router = useRouter()

onMounted(async () => {
  if (!sessions.loaded) await sessions.fetchAll()
})

const items = computed(() => {
  const limit = props.limit ?? 8
  return [...sessions.list]
    .sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))
    .slice(0, limit)
})

function open(id: string) {
  router.push(`/c/${id}`)
}
</script>

<template>
  <Card class="border-border/60 shadow-none">
    <CardHeader class="pb-2">
      <CardTitle class="flex items-center gap-2 text-sm">
        <Activity class="size-3.5 text-pink-500" />
        最近活動
      </CardTitle>
    </CardHeader>
    <CardContent class="space-y-1">
      <template v-if="!sessions.loaded && sessions.loading">
        <Skeleton v-for="i in 5" :key="i" class="h-10 w-full" />
      </template>
      <template v-else-if="items.length === 0">
        <p class="py-4 text-center text-xs text-muted-foreground">尚無 session</p>
      </template>
      <template v-else>
        <button
          v-for="s in items"
          :key="s.session_id"
          type="button"
          class="group flex w-full items-center gap-3 rounded-md px-2 py-2 text-left transition-colors hover:bg-muted/60"
          @click="open(s.session_id)"
        >
          <div
            class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-pink-500/15 dark:bg-pink-500/20"
          >
            <MessageSquare class="size-4 text-pink-600 dark:text-pink-400" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <span class="truncate text-xs font-medium">
                {{ s.title || s.session_id.slice(0, 8) }}
              </span>
              <span class="shrink-0 text-[10px] text-muted-foreground">
                {{ relativeTime(s.updated_at || '') }}
              </span>
            </div>
            <p class="truncate text-[11px] text-muted-foreground">
              {{ truncate(s.last_user_message || s.last_assistant_preview || '尚無訊息', 60) }}
            </p>
          </div>
          <ArrowRight
            class="size-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
          />
        </button>
      </template>
    </CardContent>
  </Card>
</template>

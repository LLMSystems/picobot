<script setup lang="ts">
import { watch } from 'vue'
import { useRouter } from 'vue-router'
import MessageList from '@/components/chat/MessageList.vue'
import Composer from '@/components/chat/Composer.vue'
import { useChatStore } from '@/stores/chat'
import { useSessionsStore } from '@/stores/sessions'

const props = defineProps<{ id: string }>()
const chat = useChatStore()
const sessions = useSessionsStore()
const router = useRouter()

watch(
  () => props.id,
  async (id) => {
    if (!id) return
    if (sessions.loaded && !sessions.findById(id)) {
      router.replace('/')
      return
    }
    await chat.switchTo(id)
  },
  { immediate: true },
)

watch(
  () => sessions.loaded,
  (loaded) => {
    if (loaded && !sessions.findById(props.id)) {
      router.replace('/')
    }
  },
)
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <MessageList class="flex-1 min-h-0" />
    <Composer />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import PicobotIcon from '@/components/common/PicobotIcon.vue'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/lib/errors'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const error = ref('')
const submitting = ref(false)

async function submit() {
  if (submitting.value) return
  error.value = ''
  submitting.value = true
  try {
    await auth.login(username.value.trim(), password.value)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    await router.replace(redirect)
  } catch (err) {
    error.value =
      err instanceof ApiError && err.status === 401
        ? '帳號或密碼錯誤'
        : err instanceof Error
          ? err.message
          : '登入失敗'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="flex min-h-screen w-full items-center justify-center bg-background px-6 py-12">
    <div class="w-full max-w-sm">
      <div class="mb-8 flex flex-col items-center gap-3 text-center">
        <PicobotIcon :size="72" variant="idle" state="idle" />
        <h1 class="text-2xl font-semibold tracking-tight">登入 Picobot</h1>
        <p class="text-sm text-muted-foreground">輸入你的帳號密碼以繼續</p>
      </div>

      <form class="space-y-4" @submit.prevent="submit">
        <div class="space-y-1.5">
          <Label for="username">帳號</Label>
          <Input
            id="username"
            v-model="username"
            autocomplete="username"
            placeholder="你的帳號"
            required
          />
        </div>
        <div class="space-y-1.5">
          <Label for="password">密碼</Label>
          <Input
            id="password"
            v-model="password"
            type="password"
            autocomplete="current-password"
            placeholder="••••••••"
            required
          />
        </div>

        <p v-if="error" class="text-sm text-destructive">{{ error }}</p>

        <Button type="submit" class="w-full" :disabled="submitting">
          {{ submitting ? '登入中…' : '登入' }}
        </Button>
      </form>

      <p class="mt-6 text-center text-sm text-muted-foreground">
        還沒有帳號？
        <RouterLink to="/register" class="font-medium text-brand hover:underline">
          建立帳號
        </RouterLink>
      </p>
    </div>
  </div>
</template>

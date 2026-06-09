<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import PicobotIcon from '@/components/common/PicobotIcon.vue'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/lib/errors'

const auth = useAuthStore()
const router = useRouter()

const username = ref('')
const password = ref('')
const confirm = ref('')
const error = ref('')
const submitting = ref(false)

const MIN_PASSWORD = 8

async function submit() {
  if (submitting.value) return
  error.value = ''
  if (password.value.length < MIN_PASSWORD) {
    error.value = `密碼至少需要 ${MIN_PASSWORD} 個字元`
    return
  }
  if (password.value !== confirm.value) {
    error.value = '兩次輸入的密碼不一致'
    return
  }
  submitting.value = true
  try {
    await auth.register(username.value.trim(), password.value)
    await router.replace('/')
  } catch (err) {
    if (err instanceof ApiError && err.code === 'USERNAME_TAKEN') {
      error.value = '這個帳號已被使用'
    } else if (err instanceof ApiError && err.code === 'WEAK_PASSWORD') {
      error.value = '密碼強度不足，請使用更長的密碼'
    } else {
      error.value = err instanceof Error ? err.message : '註冊失敗'
    }
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
        <h1 class="text-2xl font-semibold tracking-tight">建立 Picobot 帳號</h1>
        <p class="text-sm text-muted-foreground">註冊後即可開始你的對話</p>
      </div>

      <form class="space-y-4" @submit.prevent="submit">
        <div class="space-y-1.5">
          <Label for="username">帳號</Label>
          <Input
            id="username"
            v-model="username"
            autocomplete="username"
            placeholder="選一個帳號名稱"
            required
          />
        </div>
        <div class="space-y-1.5">
          <Label for="password">密碼</Label>
          <Input
            id="password"
            v-model="password"
            type="password"
            autocomplete="new-password"
            placeholder="至少 8 個字元"
            required
          />
        </div>
        <div class="space-y-1.5">
          <Label for="confirm">確認密碼</Label>
          <Input
            id="confirm"
            v-model="confirm"
            type="password"
            autocomplete="new-password"
            placeholder="再輸入一次密碼"
            required
          />
        </div>

        <p v-if="error" class="text-sm text-destructive">{{ error }}</p>

        <Button type="submit" class="w-full" :disabled="submitting">
          {{ submitting ? '建立中…' : '建立帳號' }}
        </Button>
      </form>

      <p class="mt-6 text-center text-sm text-muted-foreground">
        已經有帳號了？
        <RouterLink to="/login" class="font-medium text-brand hover:underline">
          前往登入
        </RouterLink>
      </p>
    </div>
  </div>
</template>

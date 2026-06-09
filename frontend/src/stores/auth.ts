import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/lib/api'
import type { AuthUser } from '@/lib/types'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)
  // `ready` flips true once we've resolved the initial session probe, so the
  // router guard can wait instead of bouncing a logged-in user to /login on
  // the first paint.
  const ready = ref(false)

  const isAuthenticated = computed(() => user.value !== null)
  const isAdmin = computed(() => user.value?.is_admin === true)

  /** Resolve the current session from the cookie. Safe to call repeatedly. */
  async function fetchMe(): Promise<void> {
    try {
      user.value = await api.authMe()
    } catch {
      user.value = null
    } finally {
      ready.value = true
    }
  }

  async function login(username: string, password: string): Promise<void> {
    user.value = await api.authLogin({ username, password })
  }

  async function register(username: string, password: string): Promise<void> {
    user.value = await api.authRegister({ username, password })
  }

  async function logout(): Promise<void> {
    try {
      await api.authLogout()
    } finally {
      user.value = null
    }
  }

  /** Drop local auth state without a network call (used on a 401). */
  function reset(): void {
    user.value = null
  }

  return { user, ready, isAuthenticated, isAdmin, fetchMe, login, register, logout, reset }
})

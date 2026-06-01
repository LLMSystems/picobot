import { ref } from 'vue'
import { api } from '@/lib/api'

export interface BrowserTab {
  targetId: string
  title: string
  url: string
}

export function useBrowserTabs() {
  const tabs = ref<BrowserTab[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function refresh(): Promise<BrowserTab[]> {
    loading.value = true
    error.value = null
    try {
      const res = await api.listBrowserTabs()
      tabs.value = res.tabs
      return res.tabs
    } catch (e) {
      error.value = e instanceof Error ? e.message : '無法取得分頁列表'
      return tabs.value
    } finally {
      loading.value = false
    }
  }

  async function open(url?: string): Promise<string | null> {
    try {
      const res = await api.createBrowserTab(url ? { url } : {})
      await refresh()
      return res.targetId
    } catch (e) {
      error.value = e instanceof Error ? e.message : '無法開啟新分頁'
      return null
    }
  }

  async function close(targetId: string): Promise<boolean> {
    try {
      await api.closeBrowserTab(targetId)
      await refresh()
      return true
    } catch (e) {
      error.value = e instanceof Error ? e.message : '無法關閉分頁'
      return false
    }
  }

  return { tabs, loading, error, refresh, open, close }
}

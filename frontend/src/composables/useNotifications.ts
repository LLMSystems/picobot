import { computed, ref } from 'vue'

const STORAGE_KEY = 'picobot:notifications:enabled'

function readStored(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

function writeStored(v: boolean) {
  try {
    localStorage.setItem(STORAGE_KEY, v ? '1' : '0')
  } catch {
    // ignore
  }
}

const enabled = ref(readStored())
const permission = ref<NotificationPermission>(
  typeof Notification !== 'undefined' ? Notification.permission : 'denied',
)

export function useNotifications() {
  const supported = typeof Notification !== 'undefined'

  const canNotify = computed(
    () => supported && enabled.value && permission.value === 'granted',
  )

  async function enable(): Promise<boolean> {
    if (!supported) return false
    if (permission.value === 'default') {
      try {
        const result = await Notification.requestPermission()
        permission.value = result
      } catch {
        return false
      }
    }
    if (permission.value === 'granted') {
      enabled.value = true
      writeStored(true)
      return true
    }
    return false
  }

  function disable() {
    enabled.value = false
    writeStored(false)
  }

  async function toggle(): Promise<boolean> {
    if (enabled.value) {
      disable()
      return false
    }
    return enable()
  }

  function notify(title: string, body?: string) {
    if (!canNotify.value) return
    if (typeof document !== 'undefined' && document.hasFocus()) return
    try {
      const n = new Notification(title, {
        body,
        icon: '/favicon.ico',
        tag: 'picobot-stream-done',
      })
      n.onclick = () => {
        try {
          window.focus()
          n.close()
        } catch {
          // ignore
        }
      }
    } catch {
      // ignore
    }
  }

  /**
   * Force a notification even when the document has focus — used for alert
   * events where the user should hear about a problem regardless of where
   * their attention is.
   */
  function notifyAlert(opts: { title: string; body?: string; tag: string }) {
    if (!canNotify.value) return
    try {
      const n = new Notification(opts.title, {
        body: opts.body,
        icon: '/favicon.ico',
        tag: opts.tag,
        requireInteraction: true,
      })
      n.onclick = () => {
        try {
          window.focus()
          n.close()
        } catch {
          // ignore
        }
      }
    } catch {
      // ignore
    }
  }

  return {
    supported,
    enabled,
    permission,
    canNotify,
    enable,
    disable,
    toggle,
    notify,
    notifyAlert,
  }
}

// Map from KeyboardEvent.key / .code to Windows virtual-key codes.
// CDP Input.dispatchKeyEvent often needs windowsVirtualKeyCode for non-character
// keys (Enter, Backspace, Arrow*, Tab, etc.) to fire page-level handlers.

const KEY_TO_VK: Record<string, number> = {
  Backspace: 8,
  Tab: 9,
  Enter: 13,
  Shift: 16,
  Control: 17,
  Alt: 18,
  Pause: 19,
  CapsLock: 20,
  Escape: 27,
  ' ': 32,
  PageUp: 33,
  PageDown: 34,
  End: 35,
  Home: 36,
  ArrowLeft: 37,
  ArrowUp: 38,
  ArrowRight: 39,
  ArrowDown: 40,
  Insert: 45,
  Delete: 46,
  Meta: 91,
  ContextMenu: 93,
  F1: 112,
  F2: 113,
  F3: 114,
  F4: 115,
  F5: 116,
  F6: 117,
  F7: 118,
  F8: 119,
  F9: 120,
  F10: 121,
  F11: 122,
  F12: 123,
}

const CODE_TO_VK: Record<string, number> = {
  Numpad0: 96,
  Numpad1: 97,
  Numpad2: 98,
  Numpad3: 99,
  Numpad4: 100,
  Numpad5: 101,
  Numpad6: 102,
  Numpad7: 103,
  Numpad8: 104,
  Numpad9: 105,
  NumpadMultiply: 106,
  NumpadAdd: 107,
  NumpadSubtract: 109,
  NumpadDecimal: 110,
  NumpadDivide: 111,
  NumpadEnter: 13,
}

export function virtualKeyCodeFor(e: KeyboardEvent): number | undefined {
  const byKey = KEY_TO_VK[e.key]
  if (byKey !== undefined) return byKey
  const byCode = CODE_TO_VK[e.code]
  if (byCode !== undefined) return byCode
  // Letters: use uppercase char code (A-Z = 65-90)
  if (e.key.length === 1) {
    const c = e.key.toUpperCase().charCodeAt(0)
    if (c >= 0x30 && c <= 0x39) return c // 0-9
    if (c >= 0x41 && c <= 0x5a) return c // A-Z
  }
  return undefined
}

// Keys that should still send `text` in dispatchKeyEvent (besides char events),
// so the page sees the proper input.
const TEXT_KEYS: Record<string, string> = {
  Enter: '\r',
  Tab: '\t',
}

export function textForKey(e: KeyboardEvent): string | undefined {
  return TEXT_KEYS[e.key]
}

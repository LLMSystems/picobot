import type { ToolCapability } from './types'

// Frontend-side fallback. Backend's `display_name` / `description_zh` win when
// present; this map covers cases where capabilities haven't loaded yet, or
// tools that the backend doesn't know about (e.g. when capabilities is stale).
const FALLBACK_NAMES: Record<string, string> = {
  read_file: '讀取檔案',
  write_file: '寫入檔案',
  edit_file: '編輯檔案',
  list_dir: '列出資料夾',
  glob: '搜尋路徑',
  grep: '搜尋內容',
  exec: '執行指令',
  spawn: '派發子代理',
  list_subagents: '列出子代理',
  subagent_status: '子代理狀態',
  subagent_wait: '等待子代理',
  tavily_search: 'Tavily 搜尋',
  read_skill: '讀取 skill',
  read_pdf: '讀取 PDF',
  read_docx: '讀取 Word',
  read_xlsx: '讀取 Excel',
  echo: '回音',
  get_weather: '查詢天氣',
  calculator: '計算機',
}

const FALLBACK_DESCRIPTIONS: Record<string, string> = {
  read_file: '讀取工作區內的檔案內容',
  write_file: '建立或覆寫工作區檔案',
  edit_file: '對檔案做字串替換式編輯',
  list_dir: '列出資料夾內的檔案',
  glob: '用萬用字元搜尋檔案路徑',
  grep: '在檔案內容中搜尋關鍵字',
  exec: '在工作區內執行 shell 指令',
  spawn: '建立並執行一個子代理任務',
  list_subagents: '查看目前的子代理列表',
  subagent_status: '查詢單一子代理的執行狀態',
  subagent_wait: '等待子代理完成並取得結果',
  tavily_search: '用 Tavily 搜尋網路資訊',
  read_skill: '讀取技能定義',
  read_pdf: '解析 PDF 檔案內容',
  read_docx: '解析 .docx 檔案內容',
  read_xlsx: '解析 .xlsx 試算表內容',
  echo: '回傳輸入內容（測試用）',
  get_weather: '查詢城市天氣（範例工具）',
  calculator: '計算數學表達式（範例工具）',
}

const CATEGORY_LABELS: Record<string, string> = {
  filesystem: '檔案',
  shell: '終端',
  mcp: 'MCP',
  search: '搜尋',
  other: '其他',
}

export function toolDisplayName(
  name: string,
  meta?: ToolCapability | null,
): string {
  if (meta?.display_name && meta.display_name.trim()) {
    return meta.display_name
  }
  return FALLBACK_NAMES[name] ?? name
}

export function toolDescription(
  name: string,
  meta?: ToolCapability | null,
): string {
  if (meta?.description_zh && meta.description_zh.trim()) {
    return meta.description_zh
  }
  if (FALLBACK_DESCRIPTIONS[name]) return FALLBACK_DESCRIPTIONS[name]
  return meta?.description ?? ''
}

export function toolCategoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category
}

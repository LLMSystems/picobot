// Centralised colour palette used by dashboard stat cards, icon tints, and
// chart accents. Keep this in one file so the visual language stays coherent
// when new metrics are added.

export type AccentColor =
  | 'green'
  | 'emerald'
  | 'blue'
  | 'sky'
  | 'purple'
  | 'violet'
  | 'orange'
  | 'amber'
  | 'pink'
  | 'rose'
  | 'cyan'
  | 'slate'

export interface AccentClasses {
  iconBg: string
  iconText: string
  pillBg: string
  pillText: string
  ring: string
  hexLine: string
  hexArea: string
}

// Per-accent Tailwind classes + raw hex for echarts. Hard-coding the hex
// avoids a runtime CSS-variable lookup; the palette stays in sync because all
// values live in one place.
export const ACCENTS: Record<AccentColor, AccentClasses> = {
  green: {
    iconBg: 'bg-green-500/15 dark:bg-green-500/20',
    iconText: 'text-green-600 dark:text-green-400',
    pillBg: 'bg-green-500/15 dark:bg-green-500/20',
    pillText: 'text-green-700 dark:text-green-300',
    ring: 'border-green-500/40',
    hexLine: '#22c55e',
    hexArea: 'rgba(34, 197, 94, 0.18)',
  },
  emerald: {
    iconBg: 'bg-emerald-500/15 dark:bg-emerald-500/20',
    iconText: 'text-emerald-600 dark:text-emerald-400',
    pillBg: 'bg-emerald-500/15 dark:bg-emerald-500/20',
    pillText: 'text-emerald-700 dark:text-emerald-300',
    ring: 'border-emerald-500/40',
    hexLine: '#10b981',
    hexArea: 'rgba(16, 185, 129, 0.18)',
  },
  blue: {
    iconBg: 'bg-blue-500/15 dark:bg-blue-500/20',
    iconText: 'text-blue-600 dark:text-blue-400',
    pillBg: 'bg-blue-500/15 dark:bg-blue-500/20',
    pillText: 'text-blue-700 dark:text-blue-300',
    ring: 'border-blue-500/40',
    hexLine: '#3b82f6',
    hexArea: 'rgba(59, 130, 246, 0.18)',
  },
  sky: {
    iconBg: 'bg-sky-500/15 dark:bg-sky-500/20',
    iconText: 'text-sky-600 dark:text-sky-400',
    pillBg: 'bg-sky-500/15 dark:bg-sky-500/20',
    pillText: 'text-sky-700 dark:text-sky-300',
    ring: 'border-sky-500/40',
    hexLine: '#0ea5e9',
    hexArea: 'rgba(14, 165, 233, 0.18)',
  },
  purple: {
    iconBg: 'bg-purple-500/15 dark:bg-purple-500/20',
    iconText: 'text-purple-600 dark:text-purple-400',
    pillBg: 'bg-purple-500/15 dark:bg-purple-500/20',
    pillText: 'text-purple-700 dark:text-purple-300',
    ring: 'border-purple-500/40',
    hexLine: '#a855f7',
    hexArea: 'rgba(168, 85, 247, 0.18)',
  },
  violet: {
    iconBg: 'bg-violet-500/15 dark:bg-violet-500/20',
    iconText: 'text-violet-600 dark:text-violet-400',
    pillBg: 'bg-violet-500/15 dark:bg-violet-500/20',
    pillText: 'text-violet-700 dark:text-violet-300',
    ring: 'border-violet-500/40',
    hexLine: '#8b5cf6',
    hexArea: 'rgba(139, 92, 246, 0.18)',
  },
  orange: {
    iconBg: 'bg-orange-500/15 dark:bg-orange-500/20',
    iconText: 'text-orange-600 dark:text-orange-400',
    pillBg: 'bg-orange-500/15 dark:bg-orange-500/20',
    pillText: 'text-orange-700 dark:text-orange-300',
    ring: 'border-orange-500/40',
    hexLine: '#f97316',
    hexArea: 'rgba(249, 115, 22, 0.18)',
  },
  amber: {
    iconBg: 'bg-amber-500/15 dark:bg-amber-500/20',
    iconText: 'text-amber-600 dark:text-amber-400',
    pillBg: 'bg-amber-500/15 dark:bg-amber-500/20',
    pillText: 'text-amber-700 dark:text-amber-300',
    ring: 'border-amber-500/40',
    hexLine: '#f59e0b',
    hexArea: 'rgba(245, 158, 11, 0.18)',
  },
  pink: {
    iconBg: 'bg-pink-500/15 dark:bg-pink-500/20',
    iconText: 'text-pink-600 dark:text-pink-400',
    pillBg: 'bg-pink-500/15 dark:bg-pink-500/20',
    pillText: 'text-pink-700 dark:text-pink-300',
    ring: 'border-pink-500/40',
    hexLine: '#ec4899',
    hexArea: 'rgba(236, 72, 153, 0.18)',
  },
  rose: {
    iconBg: 'bg-rose-500/15 dark:bg-rose-500/20',
    iconText: 'text-rose-600 dark:text-rose-400',
    pillBg: 'bg-rose-500/15 dark:bg-rose-500/20',
    pillText: 'text-rose-700 dark:text-rose-300',
    ring: 'border-rose-500/40',
    hexLine: '#f43f5e',
    hexArea: 'rgba(244, 63, 94, 0.18)',
  },
  cyan: {
    iconBg: 'bg-cyan-500/15 dark:bg-cyan-500/20',
    iconText: 'text-cyan-600 dark:text-cyan-400',
    pillBg: 'bg-cyan-500/15 dark:bg-cyan-500/20',
    pillText: 'text-cyan-700 dark:text-cyan-300',
    ring: 'border-cyan-500/40',
    hexLine: '#06b6d4',
    hexArea: 'rgba(6, 182, 212, 0.18)',
  },
  slate: {
    iconBg: 'bg-slate-500/15 dark:bg-slate-500/20',
    iconText: 'text-slate-600 dark:text-slate-400',
    pillBg: 'bg-slate-500/15 dark:bg-slate-500/20',
    pillText: 'text-slate-700 dark:text-slate-300',
    ring: 'border-slate-500/40',
    hexLine: '#64748b',
    hexArea: 'rgba(100, 116, 139, 0.18)',
  },
}

export function accent(color: AccentColor): AccentClasses {
  return ACCENTS[color]
}

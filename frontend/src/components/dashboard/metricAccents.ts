// Single source of truth for "which accent represents which metric kind".
// Anywhere in the dashboard that surfaces a given metric — stat card icon,
// chart line, list-row dot — looks it up here so the colour stays coherent.
//
// Add new metric keys as new gauges appear; the dashboard view files should
// not hard-code accent names directly.

import type { AccentColor } from './colors'

/** Logical metric keys used across the dashboard surface. */
export type MetricKey =
  // system
  | 'cpu'
  | 'memory'
  | 'threads'
  | 'db'
  | 'workspace'
  | 'sse'
  | 'chrome'
  | 'sessions'
  // agent
  | 'iterations'
  | 'tool_calls'
  | 'tool_success'
  | 'new_sessions'
  // subagents
  | 'subagent_running'
  | 'subagent_runs'
  | 'subagent_success'
  | 'subagent_p95'
  // tokens / usage
  | 'tokens'
  | 'tokens_in'
  | 'tokens_out'
  | 'models'
  // api
  | 'qps'
  | 'latency'
  | 'errors'
  | 'endpoints'
  // status pills (for HealthSummary)
  | 'healthy'
  | 'warn'
  | 'degraded'
  | 'idle'

export const METRIC_ACCENTS: Record<MetricKey, AccentColor> = {
  // system — cool palette (blue family) for steady resources
  cpu: 'blue',
  memory: 'sky',
  threads: 'slate',
  db: 'purple',
  workspace: 'violet',
  sse: 'cyan',
  chrome: 'emerald',
  sessions: 'green',

  // agent — warm + accent palette
  iterations: 'blue',
  tool_calls: 'orange',
  tool_success: 'green',
  new_sessions: 'pink',

  // subagents — violet family (kept consistent across all subagent gauges)
  subagent_running: 'violet',
  subagent_runs: 'purple',
  subagent_success: 'emerald',
  subagent_p95: 'amber',

  // tokens / usage — purple/pink axis
  tokens: 'purple',
  tokens_in: 'purple',
  tokens_out: 'pink',
  models: 'cyan',

  // api
  qps: 'cyan',
  latency: 'amber',
  errors: 'rose',
  endpoints: 'cyan',

  // status pills
  healthy: 'green',
  warn: 'amber',
  degraded: 'rose',
  idle: 'slate',
}

export function metricAccent(key: MetricKey): AccentColor {
  return METRIC_ACCENTS[key]
}

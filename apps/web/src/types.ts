export type RunSummary = {
  run_id: string
  session_id?: string | null
  trace_path: string | null
  task: string | null
  status: string | null
  model: string | null
  provider: string | null
  started_at: string | null
  submitted_at?: string | null
  duration_seconds: number | null
  iterations: number | null
  max_iterations: number | null
  total_events: number | null
  failure_category: string | null
  is_active?: boolean
  stream_path?: string | null
}

export type RunEvent = {
  index: number
  type: string
  ts: string | null
  payload: Record<string, unknown>
}

export type RunDetail = {
  run_id: string
  trace_path: string
  stream_path?: string
  is_active?: boolean
  summary: {
    run_id: string | null
    session_id?: string | null
    status: string | null
    task: string | null
    model: string | null
    failure_category: string | null
    iterations: number | null
    max_iterations: number | null
    total_events: number
    duration_seconds: number | null
    event_counts: Record<string, number>
    metrics: Record<string, unknown>
    tool_counts: Record<string, number>
    timing?: Record<string, unknown>
    final_answer?: string | null
    modified_files?: string[]
  }
}

export type LaunchRunRequest = {
  task: string
  model_profile: string
  max_iterations: number
  notes_mode: 'none' | 'auto'
  session_id?: string | null
}

export type RunStateEvent = {
  run_id: string
  session_id?: string | null
  status: string
  is_active: boolean
  trace_available: boolean
  submitted_at: string | null
  started_at: string | null
  ended_at: string | null
  error: string | null
}

export type ThreadSummary = {
  session_id: string
  task: string | null
  status: string | null
  summary: string
  created_at: string | null
  updated_at: string | null
  run_count: number
  latest_run_id: string | null
  is_active: boolean
  latest_run_status?: string | null
}

export type ThreadDetail = {
  session_id: string
  summary: string
  cwd: string
  created_at: string | null
  updated_at: string | null
  turn_count: number
  latest_run_id: string | null
  is_active: boolean
  runs: RunSummary[]
}

import type {
  LaunchRunRequest,
  RunDetail,
  RunEvent,
  RunSummary,
  ThreadDetail,
  ThreadSummary,
} from './types'

const API_BASE = import.meta.env.VITE_API_BASE ?? '/api'

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`)
  }
  return (await response.json()) as T
}

async function sendJson<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers ?? {}),
    },
  })
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`)
  }
  return (await response.json()) as T
}

export async function fetchRuns(): Promise<RunSummary[]> {
  const payload = await getJson<{ runs: RunSummary[] }>('/runs')
  return payload.runs
}

export async function fetchThreads(): Promise<ThreadSummary[]> {
  const payload = await getJson<{ threads: ThreadSummary[] }>('/threads')
  return payload.threads
}

export async function fetchThread(sessionId: string): Promise<ThreadDetail> {
  const payload = await getJson<{ thread: ThreadDetail }>(`/threads/${sessionId}`)
  return payload.thread
}

export async function fetchRun(runId: string): Promise<RunDetail> {
  const payload = await getJson<{ run: RunDetail }>(`/runs/${runId}`)
  return payload.run
}

export async function fetchRunEvents(
  runId: string,
  eventTypes: string[],
): Promise<RunEvent[]> {
  const params = new URLSearchParams()
  for (const type of eventTypes) {
    params.append('event_type', type)
  }
  const query = params.toString()
  const payload = await getJson<{ run_id: string; events: RunEvent[] }>(
    `/runs/${runId}/events${query ? `?${query}` : ''}`,
  )
  return payload.events
}

export async function createRun(request: LaunchRunRequest): Promise<RunSummary> {
  const payload = await sendJson<{ run: RunSummary }>('/runs', {
    method: 'POST',
    body: JSON.stringify(request),
  })
  return payload.run
}

export function openRunStream(
  runId: string,
  options: { fromIndex?: number; eventTypes?: string[] } = {},
): EventSource {
  const base = API_BASE.startsWith('http')
    ? API_BASE
    : `${window.location.origin}${API_BASE}`
  const params = new URLSearchParams()
  params.set('from_index', String(options.fromIndex ?? 0))
  for (const eventType of options.eventTypes ?? []) {
    params.append('event_type', eventType)
  }
  return new EventSource(`${base}/runs/${runId}/stream?${params.toString()}`)
}

import { useEffect, useMemo, useRef, useState } from 'react'
import { createRun, fetchRun, fetchRunEvents, fetchThread, fetchThreads, openRunStream } from '../api'
import { Composer } from '../components/Composer'
import { ThreadRow } from '../components/ThreadRow'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { cx } from '../components/ui/cx'
import type {
  LaunchRunRequest,
  RunDetail,
  RunEvent,
  RunStateEvent,
  ThreadDetail,
  ThreadSummary,
} from '../types'
import { useNavigate, useParams } from 'react-router-dom'

type InspectorTab = 'overview' | 'plan' | 'files' | 'trace' | 'context'
type RuntimeCardTone = 'blue' | 'green' | 'amber' | 'red' | 'slate'
type RuntimeCard = {
  id: string
  label: string
  tone: RuntimeCardTone
  summary: string
  detail?: string
  eventIndex?: number
}

function statusTone(status: string | null): RuntimeCardTone {
  if (!status) return 'slate'
  if (status.includes('success')) return 'green'
  if (status.includes('failed') || status.includes('error')) return 'red'
  if (status.includes('queued') || status.includes('approval')) return 'amber'
  if (status.includes('running')) return 'blue'
  return 'slate'
}

function statusLabel(status: string | null): string {
  if (!status) return 'Idle'
  return status.replace(/_/g, ' ')
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function formatRelative(value: string | null | undefined): string {
  if (!value) return '—'
  const time = new Date(value).getTime()
  if (Number.isNaN(time)) return value
  const deltaSeconds = Math.round((Date.now() - time) / 1000)
  if (deltaSeconds < 60) return `${deltaSeconds}s`
  if (deltaSeconds < 3600) return `${Math.round(deltaSeconds / 60)}m`
  if (deltaSeconds < 86400) return `${Math.round(deltaSeconds / 3600)}h`
  return `${Math.round(deltaSeconds / 86400)}d`
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : null
}

function excerpt(value: unknown, max = 160): string | undefined {
  if (typeof value !== 'string') return undefined
  const compact = value.replace(/\s+/g, ' ').trim()
  if (!compact) return undefined
  return compact.length > max ? `${compact.slice(0, max - 1)}…` : compact
}

function normalizeTitle(value: unknown, fallback: string): string {
  if (typeof value !== 'string') return fallback
  const compact = value
    .replace(/\uFFFD/g, '')
    .split('')
    .map((char) => {
      const codePoint = char.codePointAt(0) ?? 0
      return codePoint < 32 || codePoint === 127 ? ' ' : char
    })
    .join('')
    .replace(/\s+/g, ' ')
    .trim()
  return compact.length > 0 ? compact : fallback
}

function previewPayload(payload: Record<string, unknown>): string {
  const values = [
    payload.message,
    payload.final_answer,
    payload.tool_name,
    payload.note_id,
    payload.step_id,
    payload.status,
  ].filter((item) => typeof item === 'string' && item.length > 0)
  if (values.length > 0) return String(values[0])
  const keys = Object.keys(payload)
  return keys.length > 0 ? keys.slice(0, 3).join(' · ') : 'No payload'
}

function buildRuntimeCards(events: RunEvent[]): RuntimeCard[] {
  const cards: RuntimeCard[] = []
  for (const event of events) {
    if (event.type === 'context_quality_evaluated') {
      const warnings = Array.isArray(event.payload.warnings)
        ? event.payload.warnings.filter((item): item is string => typeof item === 'string')
        : []
      const score =
        typeof event.payload.score === 'number' ? event.payload.score.toFixed(3) : undefined
      if (warnings.length > 0 || score) {
        cards.push({
          id: `${event.index}-context`,
          label: 'Context signal',
          tone: warnings.length > 0 ? 'amber' : 'slate',
          summary: score ? `Context score ${score}` : 'Context evaluated',
          detail: warnings[0],
          eventIndex: event.index,
        })
      }
      continue
    }

    if (event.type === 'plan_created' || event.type === 'plan_updated') {
      const plan = Array.isArray(event.payload.plan) ? event.payload.plan : []
      cards.push({
        id: `${event.index}-plan`,
        label: 'Plan update',
        tone: 'blue',
        summary: `${plan.length} steps tracked`,
        detail: typeof event.payload.explanation === 'string' ? event.payload.explanation : undefined,
        eventIndex: event.index,
      })
      continue
    }

    if (event.type === 'step_started' || event.type === 'step_completed') {
      cards.push({
        id: `${event.index}-${event.type}`,
        label: 'Plan step',
        tone: event.type === 'step_completed' ? 'green' : 'blue',
        summary: typeof event.payload.step === 'string' ? event.payload.step : event.type,
        detail: typeof event.payload.status === 'string' ? event.payload.status : undefined,
        eventIndex: event.index,
      })
      continue
    }

    if (event.type === 'policy_decision') {
      const decision = asRecord(event.payload.decision)
      if (decision?.allowed === false) {
        cards.push({
          id: `${event.index}-policy`,
          label: 'Approval request',
          tone: 'amber',
          summary: typeof event.payload.tool_name === 'string' ? event.payload.tool_name : 'Tool blocked',
          detail: typeof decision.reason === 'string' ? decision.reason : undefined,
          eventIndex: event.index,
        })
      }
      continue
    }

    if (event.type === 'tool_result') {
      const result = asRecord(event.payload.result)
      if (!result) continue
      const toolName = typeof result.tool_name === 'string' ? result.tool_name : 'tool'
      const metadata = asRecord(result.metadata)
      const ok = result.ok === true
      if (toolName === 'run_command') {
        cards.push({
          id: `${event.index}-command`,
          label: 'Shell command',
          tone: ok ? 'blue' : 'red',
          summary: typeof metadata?.cmd === 'string' ? metadata.cmd : toolName,
          detail: excerpt(result.error) ?? excerpt(result.output),
          eventIndex: event.index,
        })
        continue
      }
      if (toolName === 'edit_file' || toolName === 'write_file') {
        cards.push({
          id: `${event.index}-file`,
          label: 'File change',
          tone: ok ? 'green' : 'red',
          summary: typeof metadata?.path === 'string' ? metadata.path : toolName,
          detail: excerpt(result.output),
          eventIndex: event.index,
        })
        continue
      }
      if (toolName === 'run_tests') {
        cards.push({
          id: `${event.index}-tests`,
          label: 'Test result',
          tone: ok ? 'green' : 'red',
          summary: typeof metadata?.cmd === 'string' ? metadata.cmd : 'run_tests',
          detail: excerpt(result.error) ?? excerpt(result.output),
          eventIndex: event.index,
        })
        continue
      }
      cards.push({
        id: `${event.index}-tool`,
        label: 'Tool call',
        tone: ok ? 'slate' : 'red',
        summary: toolName,
        detail: excerpt(result.output) ?? excerpt(result.error),
        eventIndex: event.index,
      })
      continue
    }

    if (event.type === 'run_finished') {
      cards.push({
        id: `${event.index}-finished`,
        label: event.payload.status === 'success' ? 'Completed' : 'Needs attention',
        tone: event.payload.status === 'success' ? 'green' : 'red',
        summary:
          typeof event.payload.final_answer === 'string'
            ? excerpt(event.payload.final_answer, 180) ?? statusLabel(String(event.payload.status))
            : statusLabel(typeof event.payload.status === 'string' ? event.payload.status : 'finished'),
        eventIndex: event.index,
      })
      continue
    }

    if (event.type === 'model_error') {
      cards.push({
        id: `${event.index}-error`,
        label: 'Model error',
        tone: 'red',
        summary: typeof event.payload.error_type === 'string' ? event.payload.error_type : 'Model error',
        detail: typeof event.payload.error === 'string' ? excerpt(event.payload.error) : undefined,
        eventIndex: event.index,
      })
    }
  }
  return cards.slice(-10)
}

function collectChangedFiles(detail: RunDetail | null, events: RunEvent[]): string[] {
  const files = new Set<string>()
  for (const path of detail?.summary.modified_files ?? []) {
    files.add(path)
  }
  for (const event of events) {
    if (event.type !== 'tool_result') continue
    const result = asRecord(event.payload.result)
    const metadata = asRecord(result?.metadata)
    const toolName = typeof result?.tool_name === 'string' ? result.tool_name : ''
    const path = typeof metadata?.path === 'string' ? metadata.path : null
    if (!path) continue
    if (toolName === 'edit_file' || toolName === 'write_file') {
      files.add(path)
    }
  }
  return [...files]
}

export function WorkbenchPage() {
  const navigate = useNavigate()
  const { runId = '' } = useParams()
  const [threads, setThreads] = useState<ThreadSummary[]>([])
  const [threadsLoading, setThreadsLoading] = useState(true)
  const [threadsError, setThreadsError] = useState<string | null>(null)
  const [threadDetail, setThreadDetail] = useState<ThreadDetail | null>(null)
  const [detail, setDetail] = useState<RunDetail | null>(null)
  const [events, setEvents] = useState<RunEvent[]>([])
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [streamState, setStreamState] = useState<'idle' | 'connecting' | 'live' | 'closed'>('idle')
  const [runState, setRunState] = useState<RunStateEvent | null>(null)
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>('overview')
  const [inspectorOpen, setInspectorOpen] = useState(true)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [launching, setLaunching] = useState(false)
  const [launchError, setLaunchError] = useState<string | null>(null)
  const [mode, setMode] = useState<'local' | 'worktree'>('local')
  const [permission, setPermission] = useState<'read-only' | 'safe-edit' | 'full-access'>(
    'safe-edit',
  )
  const [contextSource, setContextSource] = useState<'repo' | 'memory'>('repo')
  const [form, setForm] = useState<LaunchRunRequest>({
    task: '',
    model_profile: 'scripted',
    max_iterations: 8,
    notes_mode: 'auto',
  })
  const lastEventIndexRef = useRef(0)
  const currentSessionId = detail?.summary.session_id ?? runState?.session_id ?? null

  useEffect(() => {
    let cancelled = false
    const loadThreads = async () => {
      try {
        const nextThreads = await fetchThreads()
        if (cancelled) return
        setThreads(nextThreads)
        setThreadsError(null)
      } catch (err) {
        if (cancelled) return
        setThreadsError(err instanceof Error ? err.message : 'Failed to load threads.')
      } finally {
        if (!cancelled) setThreadsLoading(false)
      }
    }
    void loadThreads()
    const timer = window.setInterval(() => {
      void loadThreads()
    }, 3000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [])

  useEffect(() => {
    if (runId || threads.length === 0) return
    const latestRunId = threads[0].latest_run_id
    if (latestRunId) {
      navigate(`/workbench/${latestRunId}`, { replace: true })
    }
  }, [navigate, runId, threads])

  useEffect(() => {
    if (!runId) {
      queueMicrotask(() => {
        setDetail(null)
        setEvents([])
        setRunState(null)
        setThreadDetail(null)
      })
      lastEventIndexRef.current = 0
      return
    }

    let cancelled = false
    Promise.resolve().then(() => {
      if (!cancelled) {
        setDetailLoading(true)
        setDetailError(null)
      }
    })

    Promise.all([fetchRun(runId), fetchRunEvents(runId, [])])
      .then(([nextDetail, nextEvents]) => {
        if (cancelled) return
        setDetail(nextDetail)
        setEvents(nextEvents)
        const sessionId = nextDetail.summary.session_id
        if (typeof sessionId === 'string' && sessionId.length > 0) {
          void fetchThread(sessionId).then(setThreadDetail).catch(() => undefined)
        } else {
          setThreadDetail(null)
        }
        lastEventIndexRef.current =
          nextEvents.length > 0 ? nextEvents[nextEvents.length - 1].index + 1 : 0
      })
      .catch((err: Error) => {
        if (cancelled) return
        setDetailError(err.message)
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [runId])

  useEffect(() => {
    if (!runId) return
    queueMicrotask(() => {
      setStreamState('connecting')
    })
    const stream = openRunStream(runId, { fromIndex: lastEventIndexRef.current })

    stream.addEventListener('run_state', (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as RunStateEvent
      setRunState(payload)
      setStreamState(payload.is_active ? 'live' : 'closed')
      void fetchRun(runId)
        .then((nextDetail) => {
          setDetail(nextDetail)
          if (typeof nextDetail.summary.session_id === 'string' && nextDetail.summary.session_id) {
            void fetchThread(nextDetail.summary.session_id)
              .then(setThreadDetail)
              .catch(() => undefined)
          }
        })
        .catch(() => undefined)
    })

    stream.addEventListener('trace_event', (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as RunEvent
      lastEventIndexRef.current = payload.index + 1
      setEvents((current) => {
        if (current.some((item) => item.index === payload.index)) {
          return current
        }
        return [...current, payload].sort((a, b) => a.index - b.index)
      })
    })

    stream.addEventListener('end', () => {
      setStreamState('closed')
      stream.close()
      void fetchThreads().then(setThreads).catch(() => undefined)
      void fetchRun(runId).then(setDetail).catch(() => undefined)
    })

    stream.onerror = () => {
      setStreamState((current) => (current === 'closed' ? current : 'connecting'))
    }

    return () => {
      stream.close()
    }
  }, [runId])

  const currentThread = useMemo(
    () => threads.find((item) => item.session_id === currentSessionId) ?? null,
    [currentSessionId, threads],
  )
  const activeRun = useMemo(() => {
    const runs = threadDetail?.runs ?? []
    return runs.find((item) => item.run_id === runId) ?? null
  }, [runId, threadDetail])
  const runtimeCards = useMemo(() => buildRuntimeCards(events), [events])
  const changedFiles = useMemo(() => collectChangedFiles(detail, events), [detail, events])
  const planEvents = useMemo(
    () =>
      events.filter((event) =>
        ['plan_created', 'plan_updated', 'step_started', 'step_completed'].includes(event.type),
      ),
    [events],
  )
  const latestContextSignal = useMemo(
    () => [...events].reverse().find((event) => event.type === 'context_quality_evaluated') ?? null,
    [events],
  )
  const stats = useMemo(
    () => ({
      active: threads.filter((item) => item.is_active).length,
      attention: threads.filter(
        (item) => item.status && !item.is_active && item.status !== 'success',
      ).length,
      changedFiles: changedFiles.length,
    }),
    [changedFiles.length, threads],
  )
  const effectiveStatus = runState?.status ?? detail?.summary.status ?? activeRun?.status ?? 'idle'
  const selectedModel = detail?.summary.model ?? activeRun?.model ?? form.model_profile
  const finalAnswer = detail?.summary.final_answer
  const currentTaskTitle = normalizeTitle(currentThread?.task ?? detail?.summary.task, 'New task')
  const timelineLabel =
    excerpt(runtimeCards[runtimeCards.length - 1]?.summary, 72) ??
    (runState?.is_active ? 'Running' : 'Ready')

  async function handleLaunch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLaunching(true)
    setLaunchError(null)
    try {
      const run = await createRun({
        ...form,
        task: form.task.trim(),
        model_profile: form.model_profile.trim() || 'scripted',
        session_id: currentSessionId,
      })
      void fetchThreads().then(setThreads).catch(() => undefined)
      setForm((current) => ({ ...current, task: '' }))
      navigate(`/workbench/${run.run_id}`)
    } catch (err) {
      setLaunchError(err instanceof Error ? err.message : 'Failed to launch run.')
    } finally {
      setLaunching(false)
    }
  }

  function handleSelectThread(thread: ThreadSummary) {
    if (thread.latest_run_id) {
      navigate(`/workbench/${thread.latest_run_id}`)
      return
    }
    navigate('/workbench')
  }

  function handleNewThread() {
    navigate('/workbench')
    setDetail(null)
    setEvents([])
    setRunState(null)
    setThreadDetail(null)
  }

  return (
    <div className="workbench-shell">
      <header className="workbench-topbar">
        <div className="topbar-left">
          <div className="project-mark">HC</div>
          <div className="topbar-stack">
            <strong>HarnessCoder</strong>
            <span>{mode === 'local' ? 'Local workspace' : 'Worktree mode'}</span>
          </div>
        </div>
        <div className="topbar-right">
          <div className="topbar-pill">
            <span>Threads</span>
            <strong>{threads.length}</strong>
          </div>
          <div className="topbar-pill">
            <span>Live</span>
            <strong>{stats.active}</strong>
          </div>
          <div className="topbar-pill">
            <span>Attention</span>
            <strong>{stats.attention}</strong>
          </div>
          <div className={`topbar-pill tone-${statusTone(effectiveStatus)}`}>
            <span>Stream</span>
            <strong>{streamState}</strong>
          </div>
        </div>
      </header>

      <div className="workbench-frame">
        <aside className="sidebar">
          <div className="sidebar-section sidebar-head">
            <div>
              <span className="section-kicker">Project</span>
              <h1>Threads</h1>
            </div>
            <Button onClick={handleNewThread}>
              New
            </Button>
          </div>

          <div className="sidebar-section sidebar-filter-row">
            <Chip active>All</Chip>
            <Chip>Live {stats.active}</Chip>
            <Chip>Files {stats.changedFiles}</Chip>
          </div>

          <div className="thread-list">
            {threadsLoading ? <div className="empty-panel">Loading threads…</div> : null}
            {threadsError ? <div className="empty-panel error">{threadsError}</div> : null}
            {!threadsLoading && !threadsError && threads.length === 0 ? (
              <div className="empty-panel">No threads yet.</div>
            ) : null}
            {threads.map((thread) => {
              const badges = [
                ...(thread.is_active ? [{ label: 'running', tone: 'blue' as const }] : []),
                ...(thread.status && thread.status !== 'success' && !thread.is_active
                  ? [{ label: thread.status, tone: 'slate' as const }]
                  : []),
                { label: `${thread.run_count} runs`, tone: 'slate' as const },
              ]

              return (
                <ThreadRow
                  key={thread.session_id}
                  active={thread.session_id === currentSessionId}
                  title={normalizeTitle(thread.task, 'Untitled thread')}
                  sessionId={thread.session_id}
                  updatedLabel={formatRelative(thread.updated_at ?? thread.created_at)}
                  statusTone={statusTone(thread.status)}
                  badges={badges}
                  onClick={() => handleSelectThread(thread)}
                />
              )
            })}
          </div>
        </aside>

        <main className={cx('thread-stage', inspectorOpen && 'thread-stage-with-inspector')}>
          <section className="thread-header">
            <div>
              <span className="section-kicker">Current thread</span>
              <div className="thread-title-row">
                <h2>{currentTaskTitle}</h2>
                <span className={`inline-status tone-${statusTone(effectiveStatus)}`}>
                  {statusLabel(effectiveStatus)}
                </span>
              </div>
            </div>
            <div className="thread-header-meta">
              <div>
                <span>Model</span>
                <strong>{selectedModel}</strong>
              </div>
              <div>
                <span>Thread</span>
                <strong>{currentSessionId ?? 'new'}</strong>
              </div>
              <div>
                <span>Runs</span>
                <strong>{threadDetail?.turn_count ?? currentThread?.run_count ?? 0}</strong>
              </div>
            </div>
          </section>

          <section className="thread-view">
            {detailLoading ? <div className="empty-panel">Loading thread…</div> : null}
            {detailError ? <div className="empty-panel error">{detailError}</div> : null}
            {!runId && !detailLoading ? (
              <div className="empty-thread">
                <span className="section-kicker">Ready</span>
                <h3>Start a new thread from the composer.</h3>
              </div>
            ) : null}

            {runId ? (
              <>
                <article className="message-block user-block">
                  <span className="message-role">Task</span>
                  <p>{currentTaskTitle}</p>
                </article>

                <article className="message-block agent-block">
                  <div className="agent-block-head">
                    <span className="message-role">Runtime</span>
                    <Chip tone={statusTone(effectiveStatus)}>
                      {streamState}
                    </Chip>
                  </div>
                  <div className="runtime-overview">
                    <div className="runtime-overview-main">
                      <span>Status</span>
                      <strong>{statusLabel(effectiveStatus)}</strong>
                      <p>{timelineLabel}</p>
                    </div>
                    <div className="runtime-meta-strip">
                      <div>
                        <span>Iterations</span>
                        <strong>
                          {detail?.summary.iterations ?? 0}/{detail?.summary.max_iterations ?? 0}
                        </strong>
                      </div>
                      <div>
                        <span>Events</span>
                        <strong>{detail?.summary.total_events ?? 0}</strong>
                      </div>
                      <div>
                        <span>Thread</span>
                        <strong>{currentSessionId ?? 'new'}</strong>
                      </div>
                    </div>
                  </div>
                </article>

                <section className="runtime-card-stack">
                  {runtimeCards.length === 0 ? (
                    <div className="empty-panel small">No grouped runtime events yet.</div>
                  ) : (
                    runtimeCards.map((card) => (
                      <article key={card.id} className={`runtime-card tone-${card.tone}`}>
                        <div className="runtime-card-head">
                          <Chip tone={card.tone}>{card.label}</Chip>
                          {typeof card.eventIndex === 'number' ? <span>#{card.eventIndex}</span> : null}
                        </div>
                        <strong>{card.summary}</strong>
                        {card.detail ? <p>{card.detail}</p> : null}
                      </article>
                    ))
                  )}
                </section>

                {finalAnswer ? (
                  <article className="message-block summary-block-main">
                    <span className="message-role">Summary</span>
                    <p>{finalAnswer}</p>
                  </article>
                ) : null}
              </>
            ) : null}
          </section>

          <Composer
            task={form.task}
            modelProfile={form.model_profile}
            maxIterations={form.max_iterations}
            notesMode={form.notes_mode}
            mode={mode}
            permission={permission}
            contextSource={contextSource}
            advancedOpen={advancedOpen}
            launching={launching}
            launchError={launchError}
            onSubmit={handleLaunch}
            onTaskChange={(value) => setForm((current) => ({ ...current, task: value }))}
            onModeChange={setMode}
            onModelProfileChange={(value) =>
              setForm((current) => ({ ...current, model_profile: value }))
            }
            onPermissionChange={setPermission}
            onToggleAdvanced={() => setAdvancedOpen((current) => !current)}
            onMaxIterationsChange={(value) =>
              setForm((current) => ({ ...current, max_iterations: value }))
            }
            onNotesModeChange={(value) =>
              setForm((current) => ({ ...current, notes_mode: value }))
            }
            onContextSourceChange={setContextSource}
          />
        </main>

        <aside className={cx('inspector', inspectorOpen ? 'open' : 'collapsed')}>
          <div className="inspector-topline">
            {inspectorOpen ? (
              <div className="inspector-tabs">
                {(['overview', 'plan', 'files', 'trace', 'context'] as InspectorTab[]).map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    className={inspectorTab === tab ? 'inspector-tab active' : 'inspector-tab'}
                    onClick={() => setInspectorTab(tab)}
                  >
                    {tab}
                  </button>
                ))}
              </div>
            ) : null}
            <button
              type="button"
              className="inspector-toggle"
              aria-label={inspectorOpen ? 'Collapse inspector' : 'Expand inspector'}
              onClick={() => setInspectorOpen((current) => !current)}
            >
              {inspectorOpen ? '›' : '‹'}
            </button>
          </div>

          <div className={cx('inspector-body', !inspectorOpen && 'hidden')}>
            {inspectorTab === 'overview' ? (
              <div className="inspector-stack">
                <section className="inspector-panel">
                  <span className="section-kicker">Overview</span>
                  <div className="metric-list">
                    <div><span>Status</span><strong>{statusLabel(effectiveStatus)}</strong></div>
                    <div><span>Model</span><strong>{selectedModel}</strong></div>
                    <div><span>Thread</span><strong>{currentSessionId ?? '—'}</strong></div>
                    <div><span>Events</span><strong>{detail?.summary.total_events ?? 0}</strong></div>
                  </div>
                </section>
                <section className="inspector-panel">
                  <span className="section-kicker">Environment</span>
                  <div className="metric-list">
                    <div><span>Mode</span><strong>{mode}</strong></div>
                    <div><span>Permission</span><strong>{permission}</strong></div>
                    <div><span>Stream</span><strong>{streamState}</strong></div>
                    <div><span>Files</span><strong>{changedFiles.length}</strong></div>
                  </div>
                </section>
              </div>
            ) : null}

            {inspectorTab === 'plan' ? (
              <div className="inspector-stack">
                {planEvents.length === 0 ? <div className="empty-panel small">No plan events yet.</div> : null}
                {planEvents.map((event) => (
                  <section key={event.index} className="inspector-panel">
                    <div className="runtime-card-head">
                      <Chip tone="blue">{event.type}</Chip>
                      <span>#{event.index}</span>
                    </div>
                    <strong>{previewPayload(event.payload)}</strong>
                  </section>
                ))}
              </div>
            ) : null}

            {inspectorTab === 'files' ? (
              <div className="inspector-stack">
                {changedFiles.length === 0 ? <div className="empty-panel small">No changed files yet.</div> : null}
                {changedFiles.map((file) => (
                  <section key={file} className="inspector-panel file-row">
                    <Chip tone="green">file</Chip>
                    <strong>{file}</strong>
                  </section>
                ))}
              </div>
            ) : null}

            {inspectorTab === 'trace' ? (
              <div className="trace-list">
                {events.map((event) => (
                  <button key={event.index} type="button" className="trace-row">
                    <div className="runtime-card-head">
                      <Chip tone={statusTone(event.type)}>{event.type}</Chip>
                      <span>#{event.index}</span>
                    </div>
                    <strong>{previewPayload(event.payload)}</strong>
                    <span>{formatDateTime(event.ts)}</span>
                  </button>
                ))}
              </div>
            ) : null}

            {inspectorTab === 'context' ? (
              <div className="inspector-stack">
                <section className="inspector-panel">
                  <span className="section-kicker">Context</span>
                  <div className="metric-list">
                    <div>
                      <span>Score</span>
                      <strong>
                        {typeof latestContextSignal?.payload.score === 'number'
                          ? latestContextSignal.payload.score.toFixed(3)
                          : '—'}
                      </strong>
                    </div>
                    <div>
                      <span>Warnings</span>
                      <strong>
                        {Array.isArray(latestContextSignal?.payload.warnings)
                          ? latestContextSignal.payload.warnings.length
                          : 0}
                      </strong>
                    </div>
                    <div>
                      <span>Notes injected</span>
                      <strong>{String(detail?.summary.metrics.note_injected_count ?? 0)}</strong>
                    </div>
                    <div>
                      <span>Notes retrieved</span>
                      <strong>{String(detail?.summary.metrics.note_retrieved_count ?? 0)}</strong>
                    </div>
                  </div>
                </section>
                {Array.isArray(latestContextSignal?.payload.warnings) &&
                latestContextSignal.payload.warnings.length > 0 ? (
                  latestContextSignal.payload.warnings.map((warning) => (
                    <section key={warning} className="inspector-panel">
                      <Chip tone="amber">warning</Chip>
                      <strong>{warning}</strong>
                    </section>
                  ))
                ) : (
                  <div className="empty-panel small">No context warnings.</div>
                )}
              </div>
            ) : null}
          </div>
        </aside>
      </div>
    </div>
  )
}

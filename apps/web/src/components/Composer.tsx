import type { FormEvent } from 'react'
import { Button } from './ui/Button'
import { cx } from './ui/cx'

type ComposerProps = {
  task: string
  modelProfile: string
  maxIterations: number
  notesMode: 'none' | 'auto'
  mode: 'local' | 'worktree'
  permission: 'read-only' | 'safe-edit' | 'full-access'
  contextSource: 'repo' | 'memory'
  advancedOpen: boolean
  launching: boolean
  launchError: string | null
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  onTaskChange: (value: string) => void
  onModeChange: (value: 'local' | 'worktree') => void
  onModelProfileChange: (value: string) => void
  onPermissionChange: (value: 'read-only' | 'safe-edit' | 'full-access') => void
  onToggleAdvanced: () => void
  onMaxIterationsChange: (value: number) => void
  onNotesModeChange: (value: 'none' | 'auto') => void
  onContextSourceChange: (value: 'repo' | 'memory') => void
}

function pillToneClass(isPermission: boolean): string {
  return isPermission ? 'text-[var(--amber)]' : 'text-[var(--muted)]'
}

export function Composer({
  task,
  modelProfile,
  maxIterations,
  notesMode,
  mode,
  permission,
  contextSource,
  advancedOpen,
  launching,
  launchError,
  onSubmit,
  onTaskChange,
  onModeChange,
  onModelProfileChange,
  onPermissionChange,
  onToggleAdvanced,
  onMaxIterationsChange,
  onNotesModeChange,
  onContextSourceChange,
}: ComposerProps) {
  return (
    <section className="sticky bottom-0 px-0 pt-2.5 pb-0.5">
      <form
        onSubmit={onSubmit}
        className="grid gap-2.5 rounded-3xl border border-transparent bg-[rgba(43,48,63,0.92)] px-3 py-2.5 pb-3 shadow-[0_10px_28px_rgba(2,4,12,0.16)] transition-[border-color,box-shadow,background] duration-150 focus-within:border-[rgba(117,140,235,0.42)] focus-within:shadow-[0_0_0_2px_rgba(95,120,222,0.12),0_12px_30px_rgba(2,4,12,0.18)]"
      >
        <textarea
          value={task}
          onChange={(event) => onTaskChange(event.target.value)}
          rows={3}
          placeholder="让 HarnessCoder 检查、修改、测试或解释这个 repo…"
          required
          className="min-h-[78px] w-full resize-y rounded-[18px] border-0 bg-[rgba(31,36,48,0.48)] px-3.5 py-3 text-[var(--text)] transition-[background] duration-150 outline-none focus:bg-[rgba(33,38,51,0.58)]"
        />

        <div className="flex flex-wrap items-center justify-between gap-2.5">
          <div className="flex flex-wrap items-center gap-1.5">
            <label className="min-w-fit rounded-full bg-[rgba(255,255,255,0.04)] px-2.5 py-1.5">
              <span className="text-[10px] tracking-[0.04em] text-[var(--muted)]">Mode</span>
              <select
                value={mode}
                onChange={(event) => onModeChange(event.target.value as 'local' | 'worktree')}
                className="min-w-0 border-0 bg-transparent p-0 text-xs text-[var(--text)] outline-none"
              >
                <option value="local">Local</option>
                <option value="worktree">Worktree</option>
              </select>
            </label>

            <label className="min-w-fit rounded-full bg-[rgba(255,255,255,0.04)] px-2.5 py-1.5">
              <span className="text-[10px] tracking-[0.04em] text-[var(--muted)]">Model</span>
              <input
                value={modelProfile}
                onChange={(event) => onModelProfileChange(event.target.value)}
                className="min-w-0 border-0 bg-transparent p-0 text-xs text-[var(--text)] outline-none"
              />
            </label>

            <label className="min-w-fit rounded-full bg-[rgba(255,255,255,0.04)] px-2.5 py-1.5">
              <span className={cx('text-[10px] tracking-[0.04em]', pillToneClass(true))}>
                Permission
              </span>
              <select
                value={permission}
                onChange={(event) =>
                  onPermissionChange(event.target.value as 'read-only' | 'safe-edit' | 'full-access')
                }
                className="min-w-0 border-0 bg-transparent p-0 text-xs text-[var(--text)] outline-none"
              >
                <option value="read-only">Read only</option>
                <option value="safe-edit">Safe edit</option>
                <option value="full-access">Full access</option>
              </select>
            </label>
          </div>

          <div className="ml-auto flex items-center gap-1.5">
            <Button variant="ghost" type="button" onClick={onToggleAdvanced}>
              {advancedOpen ? 'Less' : 'More'}
            </Button>
            <Button variant="primary" type="submit" disabled={launching}>
              {launching ? 'Queueing…' : 'Send'}
            </Button>
          </div>
        </div>

        {advancedOpen ? (
          <div className="flex flex-wrap gap-2 pt-1">
            <label className="grid min-w-[132px] gap-1.5 rounded-2xl bg-[rgba(255,255,255,0.022)] px-2.5 py-2">
              <span className="text-xs text-[var(--muted)]">Max iterations</span>
              <input
                type="number"
                min={1}
                max={128}
                value={maxIterations}
                onChange={(event) => onMaxIterationsChange(Number(event.target.value) || 1)}
                className="w-full border-0 bg-transparent p-0 text-[var(--text)] outline-none"
              />
            </label>

            <label className="grid min-w-[132px] gap-1.5 rounded-2xl bg-[rgba(255,255,255,0.022)] px-2.5 py-2">
              <span className="text-xs text-[var(--muted)]">Notes</span>
              <select
                value={notesMode}
                onChange={(event) => onNotesModeChange(event.target.value as 'none' | 'auto')}
                className="w-full border-0 bg-transparent p-0 text-[var(--text)] outline-none"
              >
                <option value="auto">Auto</option>
                <option value="none">None</option>
              </select>
            </label>

            <label className="grid min-w-[132px] gap-1.5 rounded-2xl bg-[rgba(255,255,255,0.022)] px-2.5 py-2">
              <span className="text-xs text-[var(--muted)]">Context</span>
              <select
                value={contextSource}
                onChange={(event) => onContextSourceChange(event.target.value as 'repo' | 'memory')}
                className="w-full border-0 bg-transparent p-0 text-[var(--text)] outline-none"
              >
                <option value="repo">Repo</option>
                <option value="memory">Memory</option>
              </select>
            </label>
          </div>
        ) : null}

        {launchError ? <div className="text-[13px] text-[var(--red)]">{launchError}</div> : null}
      </form>
    </section>
  )
}

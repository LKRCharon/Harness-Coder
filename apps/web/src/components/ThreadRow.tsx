import { Chip } from './ui/Chip'
import { cx } from './ui/cx'

type ThreadTone = 'blue' | 'green' | 'amber' | 'red' | 'slate'

const dotToneClass: Record<ThreadTone, string> = {
  blue: 'text-[var(--blue)]',
  green: 'text-[var(--green)]',
  amber: 'text-[var(--amber)]',
  red: 'text-[var(--red)]',
  slate: 'text-[var(--muted)]',
}

type Badge = {
  label: string
  tone?: ThreadTone
}

type ThreadRowProps = {
  active?: boolean
  title: string
  sessionId: string
  updatedLabel: string
  statusTone: ThreadTone
  badges: Badge[]
  onClick: () => void
}

export function ThreadRow({
  active = false,
  title,
  sessionId,
  updatedLabel,
  statusTone,
  badges,
  onClick,
}: ThreadRowProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        'relative grid min-h-[60px] w-full cursor-pointer content-center gap-1 rounded-2xl border-0 bg-transparent px-3 py-2 pl-[15px] text-left transition-[background,transform,color] duration-150',
        'hover:bg-[rgba(255,255,255,0.04)]',
        active && 'bg-[rgba(90,116,215,0.12)]',
      )}
    >
      <span
        className={cx(
          'absolute bottom-[9px] left-1 top-[9px] w-0.5 rounded-full bg-transparent transition-[background] duration-150',
          active && 'bg-[var(--blue)]',
        )}
      />
      <div className="flex items-center gap-2.5">
        <span
          className={cx(
            'size-[7px] shrink-0 rounded-full bg-current shadow-[0_0_0_4px_rgba(255,255,255,0.02)]',
            dotToneClass[statusTone],
          )}
        />
        <strong className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-[13px] leading-[1.45] font-[540]">
          {title}
        </strong>
      </div>
      <div className="flex items-center justify-between gap-3.5">
        <span className="overflow-hidden text-ellipsis whitespace-nowrap font-[var(--mono)] text-[11px] text-[var(--muted-2)]">
          {sessionId}
        </span>
        <span className="text-[11px] text-[var(--muted)]">{updatedLabel}</span>
      </div>
      <div className="flex flex-wrap items-center gap-[5px]">
        {badges.map((badge) => (
          <Chip key={`${badge.label}-${badge.tone ?? 'slate'}`} tone={badge.tone ?? 'slate'}>
            {badge.label}
          </Chip>
        ))}
      </div>
    </button>
  )
}

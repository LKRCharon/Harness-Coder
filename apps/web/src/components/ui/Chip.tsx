import type { ReactNode } from 'react'
import { cx } from './cx'

type ChipTone = 'blue' | 'green' | 'amber' | 'red' | 'slate'

const toneClass: Record<ChipTone, string> = {
  blue: 'text-[var(--blue)]',
  green: 'text-[var(--green)]',
  amber: 'text-[var(--amber)]',
  red: 'text-[var(--red)]',
  slate: 'text-[var(--muted)]',
}

type ChipProps = {
  children: ReactNode
  tone?: ChipTone
  active?: boolean
  className?: string
}

export function Chip({ children, tone = 'slate', active = false, className }: ChipProps) {
  return (
    <span
      className={cx(
        'inline-flex min-h-6 items-center rounded-full px-[9px] text-[11px] uppercase tracking-[0.04em]',
        active ? 'bg-[rgba(90,116,215,0.14)] text-[var(--text)]' : 'bg-[rgba(255,255,255,0.038)]',
        !active && toneClass[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

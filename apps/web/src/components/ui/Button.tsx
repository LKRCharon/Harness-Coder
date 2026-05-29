import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cx } from './cx'

type ButtonVariant = 'ghost' | 'primary'

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant
  children: ReactNode
}

export function Button({
  variant = 'ghost',
  className,
  children,
  type = 'button',
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cx(
        'cursor-pointer rounded-xl border border-transparent px-3.5 text-sm transition-[background,border-color,transform,color,box-shadow] duration-150',
        'min-h-9',
        variant === 'ghost' &&
          'bg-[rgba(255,255,255,0.028)] text-[var(--muted)] hover:bg-[rgba(255,255,255,0.065)]',
        variant === 'primary' &&
          'bg-[linear-gradient(180deg,rgba(159,179,255,0.98),rgba(126,146,230,0.94))] font-[680] text-[oklch(0.19_0.016_264)] shadow-[0_8px_18px_rgba(80,105,214,0.18)] hover:-translate-y-px hover:shadow-[0_10px_20px_rgba(80,105,214,0.22)] disabled:cursor-wait disabled:opacity-70',
        className,
      )}
      {...props}
    >
      {children}
    </button>
  )
}

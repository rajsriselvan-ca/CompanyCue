import clsx from 'clsx';
import type { ButtonHTMLAttributes, ReactNode } from 'react';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    'bg-brand text-white shadow-raised hover:bg-brand-strong disabled:bg-brand/50 disabled:shadow-none',
  secondary:
    'border border-line-strong bg-surface text-ink-soft hover:bg-raised disabled:text-muted',
  ghost: 'text-muted hover:bg-raised hover:text-ink',
  danger: 'bg-danger text-white hover:brightness-110',
};

export function Button({
  variant = 'primary',
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button
      className={clsx(
        'inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold',
        'transition-colors disabled:cursor-not-allowed',
        VARIANTS[variant],
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={clsx(
        'inline-block size-4 shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent',
        className,
      )}
    />
  );
}

export function Badge({
  tone = 'neutral',
  children,
}: {
  tone?: 'neutral' | 'brand' | 'positive' | 'danger';
  children: ReactNode;
}) {
  const tones = {
    neutral: 'bg-raised text-muted',
    brand: 'bg-brand-soft text-brand-strong',
    positive: 'bg-positive-soft text-positive',
    danger: 'bg-danger-soft text-danger',
  } as const;
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[0.7rem] font-semibold',
        tones[tone],
      )}
    >
      {children}
    </span>
  );
}

/** Placeholder bars shown while a section is still being written. */
export function SkeletonLines({ lines = 3 }: { lines?: number }) {
  return (
    <div aria-hidden="true" className="space-y-2">
      {Array.from({ length: lines }, (_, index) => (
        <div
          className="shimmer h-3 rounded"
          key={index}
          style={{ width: `${100 - index * 12}%` }}
        />
      ))}
    </div>
  );
}

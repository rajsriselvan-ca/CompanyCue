import { ErrorBanner } from '@/components/ReportView';

const STEPS = [
  ['Overview', 'What they do, who buys it'],
  ['People', 'Who you might be meeting'],
  ['News', 'What happened recently'],
  ['Numbers', 'Revenue, headcount, growth'],
  ['Risks', 'What could come up'],
] as const;

/**
 * The first-run screen. Not a blank canvas: it says what to type, what comes
 * back, and where it comes from, so a rep who has never seen the tool can use
 * it without being told.
 */
export function EmptyState({
  error,
  onRetry,
  onExample,
}: {
  error: string | null;
  onRetry?: () => void;
  onExample: (companyName: string) => void;
}) {
  return (
    <div className="mx-auto flex max-w-2xl flex-col items-center px-4 py-14 text-center sm:py-20">
      {error ? (
        <div className="mb-8 w-full text-left">
          <ErrorBanner message={error} onRetry={onRetry} />
        </div>
      ) : null}

      <span
        aria-hidden="true"
        className="mb-5 grid size-12 place-items-center rounded-2xl bg-brand-soft text-xl font-bold text-brand"
      >
        C
      </span>

      <h1 className="text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
        Know the company before the conversation.
      </h1>
      <p className="mt-3 max-w-lg text-[0.95rem] leading-7 text-muted">
        Type a company name. CompanyCue searches the live web, then writes a five-section
        briefing you can scan in two minutes — with the sources it used, so you can check
        anything before you repeat it.
      </p>

      <ol className="mt-9 grid w-full grid-cols-2 gap-3 text-left sm:grid-cols-5 sm:gap-2">
        {STEPS.map(([title, detail], index) => (
          <li className="rounded-lg border border-line bg-surface px-3 py-2.5" key={title}>
            <span className="font-mono text-[0.65rem] font-semibold text-brand">
              {index + 1}
            </span>
            <p className="text-xs font-semibold text-ink">{title}</p>
            <p className="mt-0.5 text-[0.7rem] leading-4 text-muted">{detail}</p>
          </li>
        ))}
      </ol>

      <div className="mt-8 flex flex-wrap items-center justify-center gap-2 text-sm text-muted">
        <span>Try</span>
        {['Stripe', 'Datadog', 'Klarna'].map((example) => (
          <button
            className="rounded-full border border-line-strong bg-surface px-3 py-1 text-sm font-medium text-ink-soft transition-colors hover:border-brand hover:text-brand-strong"
            key={example}
            onClick={() => onExample(example)}
            type="button"
          >
            {example}
          </button>
        ))}
      </div>
    </div>
  );
}

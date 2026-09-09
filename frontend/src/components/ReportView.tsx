import { ActivityFeed } from '@/components/ActivityFeed';
import { SECTION_RENDERERS, SectionCard } from '@/components/ReportSections';
import { Button, Spinner } from '@/components/ui/primitives';
import { isStreaming, type StreamState } from '@/lib/streamState';
import { formatAbsoluteTime } from '@/lib/time';
import { SECTION_ORDER } from '@/lib/types';

const PHASE_TEXT: Record<string, string> = {
  planning: 'Planning what to search for',
  searching: 'Searching the live web',
  writing: 'Writing the briefing',
};

export function ReportView({
  state,
  onRetry,
}: {
  state: StreamState;
  onRetry: () => void;
}) {
  const streaming = isStreaming(state.phase);
  const completedCount = SECTION_ORDER.filter(
    (key) => state.sections[key].status === 'complete',
  ).length;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
            {state.companyName}
          </h1>
          <p className="mt-1 text-sm text-muted" role="status">
            {streaming ? (
              <span className="inline-flex items-center gap-2 text-brand-strong">
                <Spinner className="size-3.5" />
                {state.statusMessage ?? PHASE_TEXT[state.phase] ?? 'Working'}
                <span className="text-muted">
                  · {completedCount}/{SECTION_ORDER.length} sections
                </span>
              </span>
            ) : state.phase === 'cancelled' ? (
              'Research stopped. Nothing was saved.'
            ) : state.savedSummary ? (
              `Generated ${formatAbsoluteTime(state.savedSummary.created_at)}`
            ) : (
              ''
            )}
          </p>
        </div>

        {/* Stopping lives in the sticky header, which is always reachable;
            duplicating it here just gives the user two of the same button. */}
        {streaming ? null : (
          <Button onClick={onRetry} variant="secondary">
            Research again
          </Button>
        )}
      </header>

      {state.error ? (
        <ErrorBanner
          message={state.error.message}
          onRetry={state.error.retryable ? onRetry : undefined}
        />
      ) : null}

      {state.warnings.length > 0 ? (
        <div
          className="rounded-xl border border-brand/25 bg-brand-soft px-4 py-3 text-sm text-brand-strong"
          role="status"
        >
          <p className="font-semibold">Some sections are incomplete</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {state.warnings.map((warning, index) => (
              <li key={index}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <ActivityFeed
        collapsed={!streaming}
        entries={state.activity}
        evidenceCount={state.evidenceCount}
      />

      <div className="space-y-4">
        {SECTION_ORDER.map((key) => {
          const Renderer = SECTION_RENDERERS[key];
          const section = state.sections[key];
          return (
            <SectionCard key={key} section={section} sectionKey={key}>
              <Renderer section={section} />
            </SectionCard>
          );
        })}
      </div>
    </div>
  );
}

export function ErrorBanner({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div
      className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-danger/25 bg-danger-soft px-4 py-3"
      role="alert"
    >
      <p className="text-sm leading-6 text-ink-soft">{message}</p>
      {onRetry ? (
        <Button className="shrink-0" onClick={onRetry} variant="secondary">
          Try again
        </Button>
      ) : null}
    </div>
  );
}

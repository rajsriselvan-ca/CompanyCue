import clsx from 'clsx';

import { Spinner } from '@/components/ui/primitives';
import type { ActivityEntry } from '@/lib/streamState';

/**
 * The agent's search log, shown live.
 *
 * This is the difference between "a spinner" and "the user knows something is
 * happening": every query the agent chose, whether it came back, and how many
 * new sources it added. It also doubles as the honesty check — a rep can see
 * the briefing was written from searches, not from the model's memory.
 */
export function ActivityFeed({
  entries,
  evidenceCount,
  collapsed = false,
}: {
  entries: ActivityEntry[];
  evidenceCount: number;
  collapsed?: boolean;
}) {
  if (entries.length === 0) return null;

  return (
    <details
      className="rounded-xl border border-line bg-surface shadow-raised"
      open={!collapsed}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-semibold text-ink-soft">
        <span className="flex items-center gap-2">
          Research trail
          <span className="font-normal text-muted">
            {entries.length} {entries.length === 1 ? 'search' : 'searches'}
            {evidenceCount > 0 ? ` · ${evidenceCount} sources` : ''}
          </span>
        </span>
        <span aria-hidden="true" className="text-muted">
          ▾
        </span>
      </summary>

      <ol className="border-t border-line px-4 py-3 text-sm">
        {entries.map((entry) => (
          <li className="flex items-start gap-3 py-1.5" key={entry.id}>
            <span className="mt-0.5 shrink-0">
              {entry.status === 'running' ? (
                <Spinner className="size-3.5 text-brand" />
              ) : entry.status === 'failed' ? (
                <span aria-hidden="true" className="text-danger">
                  ✕
                </span>
              ) : (
                <span aria-hidden="true" className="text-positive">
                  ✓
                </span>
              )}
            </span>

            <span className="min-w-0 flex-1">
              <span className="flex flex-wrap items-baseline gap-x-2">
                <code
                  className={clsx(
                    'rounded px-1.5 py-0.5 font-mono text-[0.7rem]',
                    entry.tool === 'news_search'
                      ? 'bg-brand-soft text-brand-strong'
                      : 'bg-raised text-muted',
                  )}
                >
                  {entry.tool}
                </code>
                <span className="min-w-0 break-words text-ink-soft">{entry.query}</span>
              </span>

              <span className="mt-0.5 block text-xs text-muted">
                {entry.status === 'running'
                  ? 'searching…'
                  : entry.message
                    ? entry.message
                    : `${entry.resultCount ?? 0} results` +
                      (entry.newSources ? ` · ${entry.newSources} new sources` : '') +
                      (entry.elapsedMs !== null ? ` · ${entry.elapsedMs}ms` : '')}
              </span>
            </span>
          </li>
        ))}
      </ol>
    </details>
  );
}

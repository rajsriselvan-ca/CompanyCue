import clsx from 'clsx';

import { Spinner } from '@/components/ui/primitives';
import { formatAbsoluteTime, formatRelativeTime } from '@/lib/time';
import type { ReportSummary } from '@/lib/types';

export function HistorySidebar({
  reports,
  loading,
  error,
  selectedId,
  onSelect,
  onDelete,
}: {
  reports: ReportSummary[];
  loading: boolean;
  error: string | null;
  selectedId: string | null;
  onSelect: (summary: ReportSummary) => void;
  onDelete: (summary: ReportSummary) => void;
}) {
  return (
    <nav
      aria-label="Report history"
      className="flex h-full flex-col border-r border-line bg-raised/50"
    >
      <div className="flex items-center gap-2 border-b border-line px-4 py-4">
        <Logo />
        <div className="min-w-0">
          <p className="text-sm font-semibold tracking-tight text-ink">CompanyCue</p>
          <p className="truncate text-[0.7rem] text-muted">Briefings before the call</p>
        </div>
      </div>

      <div className="px-4 pt-4 pb-2">
        <h2 className="text-[0.7rem] font-semibold tracking-wide text-muted uppercase">
          Recent briefings
        </h2>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
        {loading ? (
          <p className="flex items-center gap-2 px-2 py-2 text-sm text-muted">
            <Spinner className="size-3.5" /> Loading history…
          </p>
        ) : error ? (
          <p className="px-2 py-2 text-sm text-danger">{error}</p>
        ) : reports.length === 0 ? (
          <p className="px-2 py-2 text-sm leading-6 text-muted">
            Nothing here yet. Your briefings are saved automatically and stay on this machine.
          </p>
        ) : (
          <ul className="space-y-0.5">
            {reports.map((report) => {
              const selected = report.id === selectedId;
              return (
                <li className="group relative" key={report.id}>
                  <button
                    aria-current={selected ? 'true' : undefined}
                    className={clsx(
                      'w-full rounded-lg px-3 py-2 pr-9 text-left transition-colors',
                      selected ? 'bg-surface shadow-raised' : 'hover:bg-surface/70',
                    )}
                    onClick={() => onSelect(report)}
                    type="button"
                  >
                    <span className="block truncate text-sm font-medium text-ink">
                      {report.company_name}
                    </span>
                    <time
                      className="block text-[0.7rem] text-muted"
                      dateTime={report.created_at}
                      title={formatAbsoluteTime(report.created_at)}
                    >
                      {formatRelativeTime(report.created_at)}
                    </time>
                  </button>

                  <button
                    aria-label={`Delete the ${report.company_name} briefing`}
                    className="absolute top-1/2 right-1.5 -translate-y-1/2 rounded-md p-1.5 text-muted opacity-0 transition-opacity group-hover:opacity-100 hover:bg-danger-soft hover:text-danger focus-visible:opacity-100"
                    onClick={() => onDelete(report)}
                    type="button"
                  >
                    <TrashIcon />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </nav>
  );
}

function Logo() {
  return (
    <span
      aria-hidden="true"
      className="grid size-8 shrink-0 place-items-center rounded-lg bg-brand text-sm font-bold text-white"
    >
      C
    </span>
  );
}

function TrashIcon() {
  return (
    <svg fill="none" height="15" viewBox="0 0 24 24" width="15">
      <path
        d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

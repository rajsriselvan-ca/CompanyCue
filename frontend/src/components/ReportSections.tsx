import clsx from 'clsx';
import type { ReactNode } from 'react';

import { Badge, SkeletonLines, Spinner } from '@/components/ui/primitives';
import type { SectionState } from '@/lib/streamState';
import { formatNewsDate, hostnameOf } from '@/lib/time';
import {
  SECTION_LABELS,
  type FinancialHighlights,
  type NewsItem,
  type Person,
  type RiskItem,
  type SectionKey,
  type Source,
} from '@/lib/types';

/**
 * A section is "waiting" both while it streams and before it starts. Either
 * way the honest thing to show is a placeholder — "nothing was found" is a
 * finding, and claiming it before the model has written a word is a lie.
 */
function isWaiting(section: SectionState): boolean {
  return section.status === 'streaming' || section.status === 'pending';
}

/**
 * Read a section's value, preferring the finished data and falling back to the
 * partial object repaired from the in-flight stream. This is the single place
 * progressive rendering happens: everything below just draws whatever it is
 * handed, whether that is four people or the two written so far.
 */
function valueOf<T>(section: SectionState, key: string): T | null {
  if (section.data !== null && section.data !== undefined) return section.data as T;
  const partial = section.partial?.[key];
  return (partial ?? null) as T | null;
}

export function SectionCard({
  sectionKey,
  section,
  children,
}: {
  sectionKey: SectionKey;
  section: SectionState;
  children: ReactNode;
}) {
  const streaming = section.status === 'streaming';

  return (
    <section
      aria-busy={streaming || undefined}
      aria-labelledby={`section-${sectionKey}-label`}
      className={clsx(
        'rounded-xl border bg-surface p-5 shadow-panel transition-colors sm:p-6',
        streaming ? 'border-brand/40' : 'border-line',
      )}
      id={`section-${sectionKey}`}
    >
      <header className="mb-3 flex items-center justify-between gap-3">
        <h2
          className="text-sm font-semibold tracking-wide text-muted uppercase"
          id={`section-${sectionKey}-label`}
        >
          {SECTION_LABELS[sectionKey]}
        </h2>
        {streaming ? (
          <span className="flex items-center gap-1.5 text-xs font-medium text-brand">
            <Spinner className="size-3" /> writing
          </span>
        ) : section.status === 'failed' ? (
          <Badge tone="danger">unavailable</Badge>
        ) : null}
      </header>

      {section.status === 'failed' ? (
        <p className="text-sm leading-6 text-muted">
          {section.message ?? 'This section could not be completed.'}
        </p>
      ) : (
        children
      )}

      <SourceList sources={section.sources} />
    </section>
  );
}

function SourceList({ sources }: { sources: Source[] }) {
  if (sources.length === 0) return null;
  return (
    <footer className="mt-4 border-t border-line pt-3">
      <h3 className="mb-1.5 text-[0.7rem] font-semibold tracking-wide text-muted uppercase">
        Sources
      </h3>
      <ul className="flex flex-wrap gap-x-3 gap-y-1">
        {sources.map((source) => (
          <li key={source.url}>
            <a
              className="text-xs text-brand-strong underline decoration-line-strong underline-offset-2 hover:decoration-brand"
              href={source.url}
              rel="noreferrer noopener"
              target="_blank"
              title={source.title}
            >
              {hostnameOf(source.url)}
            </a>
          </li>
        ))}
      </ul>
    </footer>
  );
}

function EmptySection({ children }: { children: ReactNode }) {
  return <p className="text-sm leading-6 text-muted">{children}</p>;
}

// --- The five sections -------------------------------------------------------

export function OverviewSection({ section }: { section: SectionState }) {
  const text = valueOf<string>(section, 'overview');
  const streaming = section.status === 'streaming';

  if (!text) {
    return isWaiting(section) ? (
      <SkeletonLines lines={4} />
    ) : (
      <EmptySection>
        The search results did not identify what this company does. Try a more specific name.
      </EmptySection>
    );
  }

  return (
    <p className={clsx('text-[0.95rem] leading-7 text-ink-soft', streaming && 'streaming-caret')}>
      {text}
    </p>
  );
}

export function KeyPeopleSection({ section }: { section: SectionState }) {
  const people = valueOf<Person[]>(section, 'key_people') ?? [];

  if (people.length === 0) {
    return isWaiting(section) ? (
      <SkeletonLines lines={3} />
    ) : (
      <EmptySection>No current executives were confirmed in the search results.</EmptySection>
    );
  }

  return (
    <ul className="grid gap-2 sm:grid-cols-2">
      {people.map((person, index) => (
        <li
          className="rounded-lg border border-line bg-raised/60 px-3 py-2"
          key={`${person.name}-${index}`}
        >
          <p className="text-sm font-semibold text-ink">{person.name}</p>
          <p className="text-xs text-muted">{person.title}</p>
        </li>
      ))}
    </ul>
  );
}

export function NewsSection({ section }: { section: SectionState }) {
  const items = valueOf<NewsItem[]>(section, 'news') ?? [];

  if (items.length === 0) {
    return isWaiting(section) ? (
      <SkeletonLines lines={3} />
    ) : (
      <EmptySection>
        No material news from the past year turned up. That is itself useful: there is probably
        no recent announcement to open with.
      </EmptySection>
    );
  }

  return (
    <ul className="space-y-3">
      {items.map((item, index) => (
        <li className="border-l-2 border-brand/30 pl-3" key={`${item.headline}-${index}`}>
          <p className="text-sm font-semibold text-ink">{item.headline}</p>
          {item.summary ? (
            <p className="mt-0.5 text-sm leading-6 text-ink-soft">{item.summary}</p>
          ) : null}
          {formatNewsDate(item.date) ? (
            <p className="mt-0.5 font-mono text-[0.7rem] text-muted">
              {formatNewsDate(item.date)}
            </p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

const FINANCIAL_FIELDS: Array<[keyof FinancialHighlights, string]> = [
  ['revenue', 'Revenue'],
  ['employee_count', 'Employees'],
  ['market_cap', 'Market cap'],
  ['yoy_growth', 'YoY growth'],
];

export function FinancialsSection({ section }: { section: SectionState }) {
  const financials = valueOf<FinancialHighlights>(section, 'financials');
  const waiting = isWaiting(section);

  // Mid-stream, an all-null object means "nothing has arrived yet", not
  // "nothing exists" — four "Not disclosed" cells would read as a finished
  // answer. Wait until at least one figure has been written.
  const hasAnyValue =
    financials && FINANCIAL_FIELDS.some(([key]) => Boolean(financials[key]));

  if (!financials || (waiting && !hasAnyValue)) {
    return waiting ? (
      <SkeletonLines lines={2} />
    ) : (
      <EmptySection>No public financial figures were found.</EmptySection>
    );
  }

  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {FINANCIAL_FIELDS.map(([key, label]) => {
        const value = financials[key];
        return (
          <div className="rounded-lg border border-line bg-raised/60 px-3 py-2.5" key={key}>
            <dt className="text-[0.7rem] font-semibold tracking-wide text-muted uppercase">
              {label}
            </dt>
            <dd
              className={clsx(
                'mt-1 text-sm font-semibold',
                value ? 'text-ink' : 'text-muted italic font-normal',
              )}
            >
              {/* Explicitly "not disclosed" rather than a fabricated number. */}
              {value ?? 'Not disclosed'}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

export function RisksSection({ section }: { section: SectionState }) {
  const risks = valueOf<RiskItem[]>(section, 'risks') ?? [];

  if (risks.length === 0) {
    return isWaiting(section) ? (
      <SkeletonLines lines={2} />
    ) : (
      <EmptySection>No specific risk signals surfaced in the search results.</EmptySection>
    );
  }

  return (
    <ul className="space-y-2.5">
      {risks.map((risk, index) => (
        <li
          className="rounded-lg border border-danger/20 bg-danger-soft/50 px-3 py-2.5"
          key={`${risk.title}-${index}`}
        >
          <p className="text-sm font-semibold text-ink">{risk.title}</p>
          <p className="mt-0.5 text-sm leading-6 text-ink-soft">{risk.details}</p>
        </li>
      ))}
    </ul>
  );
}

export const SECTION_RENDERERS: Record<
  SectionKey,
  (props: { section: SectionState }) => ReactNode
> = {
  overview: OverviewSection,
  key_people: KeyPeopleSection,
  news: NewsSection,
  financials: FinancialsSection,
  risks: RisksSection,
};

import {
  AlertTriangle,
  ArrowUpRight,
  Building2,
  Check,
  CircleDollarSign,
  LoaderCircle,
  Newspaper,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  Users,
  X,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import type { ResearchReport, SectionKey, Source } from '@/lib/briefd-types';
import { sectionOrder } from '@/lib/briefd-types';
import { formatReportDate } from '@/lib/time';

const sectionMeta: Record<SectionKey, { title: string; icon: typeof Building2 }> = {
  overview: { title: 'Company overview', icon: Building2 },
  key_people: { title: 'Key people', icon: Users },
  news: { title: 'Recent news', icon: Newspaper },
  financials: { title: 'Financial highlights', icon: CircleDollarSign },
  risks: { title: 'Risk factors', icon: ShieldAlert },
};

interface ReportViewProps {
  report: ResearchReport;
  isStreaming: boolean;
  activeSection: SectionKey | null;
  completedSections: Set<SectionKey>;
  failedSections: Set<SectionKey>;
  error: string | null;
  statusMessage: string | null;
  cancelled: boolean;
  onCancel: () => void;
  onRetry: () => void;
}

function Sources({ items = [] }: { items?: Source[] }) {
  if (items.length === 0) return null;
  return (
    <div className="mt-5 flex flex-wrap gap-2 border-t border-[var(--line)] pt-4">
      <span className="mr-1 py-1 text-xs font-semibold uppercase tracking-[0.1em] text-[var(--muted-ink)]">Sources</span>
      {items.slice(0, 6).map((source) => (
        <a
          className="inline-flex max-w-[230px] items-center gap-1 rounded-full border border-[var(--line)] bg-[var(--canvas)] px-2.5 py-1 text-xs font-medium text-[var(--brand)] transition hover:border-[var(--brand)] hover:bg-[var(--brand-soft)]"
          href={source.url}
          key={source.url}
          rel="noreferrer"
          target="_blank"
        >
          <span className="truncate">{source.title}</span>
          <ArrowUpRight className="size-3 shrink-0" />
        </a>
      ))}
    </div>
  );
}

function EmptySection({ message = 'No reliable information was found for this section.' }: { message?: string }) {
  return <p className="rounded-xl bg-[var(--canvas)] px-4 py-4 text-sm leading-6 text-[var(--muted-ink)]">{message}</p>;
}

function ActivityDots({ className = '' }: { className?: string }) {
  return (
    <span aria-hidden="true" className={`inline-flex items-center gap-1 ${className}`}>
      <span className="size-1.5 animate-bounce rounded-full bg-current motion-reduce:animate-none [animation-delay:-0.3s]" />
      <span className="size-1.5 animate-bounce rounded-full bg-current motion-reduce:animate-none [animation-delay:-0.15s]" />
      <span className="size-1.5 animate-bounce rounded-full bg-current motion-reduce:animate-none" />
    </span>
  );
}

function LoadingSection({ active }: { active: boolean }) {
  return (
    <output className="block space-y-3" aria-label={active ? 'Researching section' : 'Section queued'}>
      <div className="flex items-center gap-2 text-xs font-medium text-[var(--muted-ink)]">
        <ActivityDots className={active ? 'text-[var(--brand)]' : 'text-slate-400'} />
        <span>{active ? 'Analyzing and validating…' : 'Queued for research'}</span>
      </div>
      <Skeleton className="h-3.5 w-full bg-slate-200" />
      <Skeleton className="h-3.5 w-[92%] bg-slate-200" />
      <Skeleton className="h-3.5 w-[72%] bg-slate-200" />
    </output>
  );
}

function SectionCard({
  section,
  active,
  complete,
  failed,
  pending,
  retrying,
  children,
  sources,
}: {
  section: SectionKey;
  active: boolean;
  complete: boolean;
  failed: boolean;
  pending: boolean;
  retrying: boolean;
  children: React.ReactNode;
  sources?: Source[];
}) {
  const meta = sectionMeta[section];
  const Icon = meta.icon;
  return (
    <section className={`briefing-section relative overflow-hidden rounded-2xl border bg-white p-5 shadow-[0_12px_42px_rgba(17,34,68,.045)] sm:p-7 ${active ? 'border-[var(--brand)]' : 'border-[var(--line)]'}`}>
      <div className="mb-5 flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className={`grid size-9 place-items-center rounded-xl ${active ? 'bg-[var(--brand)] text-white' : 'bg-[var(--brand-soft)] text-[var(--brand)]'}`}>
            <Icon className="size-[18px]" />
          </span>
          <div>
            <p className="text-[0.68rem] font-semibold uppercase tracking-[0.14em] text-[var(--muted-ink)]">
              {String(sectionOrder.indexOf(section) + 1).padStart(2, '0')}
            </p>
            <h2 className="text-lg font-semibold tracking-[-0.025em] text-[var(--ink)]">{meta.title}</h2>
          </div>
        </div>
        {active ? (
          <Badge className="gap-1.5 bg-[var(--brand-soft)] text-[var(--brand)]">
            <LoaderCircle className="animate-spin motion-reduce:animate-none" /> {retrying ? 'Waiting' : 'Researching'}
          </Badge>
        ) : failed ? (
          <Badge className="gap-1.5 bg-amber-50 text-amber-700">
            <AlertTriangle /> Unavailable
          </Badge>
        ) : complete ? (
          <span className="grid size-7 place-items-center rounded-full bg-emerald-50 text-emerald-600" aria-label="Complete">
            <Check className="size-4" />
          </span>
        ) : pending ? (
          <Badge className="gap-1.5 bg-slate-100 text-slate-500">
            <ActivityDots /> Queued
          </Badge>
        ) : null}
      </div>
      {children}
      {complete ? <Sources items={sources} /> : null}
    </section>
  );
}

export function ReportView({
  report,
  isStreaming,
  activeSection,
  completedSections,
  error,
  failedSections,
  statusMessage,
  cancelled,
  onCancel,
  onRetry,
}: ReportViewProps) {
  const sectionFailed = (section: SectionKey) =>
    failedSections.has(section) ||
    (report.id !== 'draft' &&
      report[section] === null &&
      report.warnings.some((warning) => warning.startsWith(sectionMeta[section].title)));
  const sectionIsComplete = (section: SectionKey) =>
    !sectionFailed(section) && (!isStreaming && report.id !== 'draft' ? true : completedSections.has(section));
  const sectionIsPending = (section: SectionKey) =>
    isStreaming && !sectionIsComplete(section) && !sectionFailed(section);

  return (
    <article className="mx-auto w-full max-w-[980px] pb-14">
      <div className="mb-6 flex flex-col gap-4 rounded-2xl bg-[var(--ink)] px-5 py-6 text-white shadow-[0_20px_60px_rgba(11,23,43,.16)] sm:flex-row sm:items-end sm:justify-between sm:px-7">
        <div>
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-white/50">
            <Sparkles className="size-3.5 text-[var(--signal)]" /> Sales briefing
          </div>
          <h1 className="text-3xl font-semibold tracking-[-0.045em] sm:text-4xl">{report.company_name}</h1>
          <p className="mt-2 text-sm text-white/48">
            {isStreaming
              ? (
                <output className="inline-flex items-center gap-2">
                  <ActivityDots className="text-[var(--signal)]" />
                  {statusMessage ?? 'Building your briefing, section by section'}
                </output>
              )
              : report.id === 'draft'
                ? cancelled
                  ? 'Research stopped before completion'
                  : 'Research was not completed'
                : `Generated ${formatReportDate(report.created_at)}`}
          </p>
        </div>
        {isStreaming ? (
          <Button className="border-white/15 bg-white/8 text-white hover:bg-white/14" onClick={onCancel} variant="outline">
            <X data-icon="inline-start" /> Stop research
          </Button>
        ) : null}
      </div>

      <ol className="mb-6 grid grid-cols-5 gap-1 rounded-2xl border border-[var(--line)] bg-white p-2" aria-label="Research progress">
        {sectionOrder.map((section, index) => {
          const complete = sectionIsComplete(section);
          const failed = sectionFailed(section);
          const active = activeSection === section;
          return (
            <li className={`flex min-w-0 items-center justify-center gap-1.5 rounded-xl px-2 py-2.5 text-xs font-semibold ${active ? 'bg-[var(--brand-soft)] text-[var(--brand)]' : failed ? 'bg-amber-50 text-amber-700' : complete ? 'text-emerald-700' : 'text-slate-400'}`} key={section}>
              {active ? <LoaderCircle className="size-3.5 shrink-0 animate-spin motion-reduce:animate-none" /> : failed ? <AlertTriangle className="size-3.5 shrink-0" /> : complete ? <Check className="size-3.5 shrink-0" /> : <span className="font-mono">{index + 1}</span>}
              <span className="hidden truncate sm:inline">{sectionMeta[section].title}</span>
            </li>
          );
        })}
      </ol>

      {error && !isStreaming ? (
        <div className="mb-6 flex flex-col gap-4 rounded-2xl border border-red-200 bg-red-50 px-5 py-4 text-red-950 sm:flex-row sm:items-center sm:justify-between" role="alert">
          <div className="flex gap-3">
            <AlertTriangle className="mt-0.5 size-5 shrink-0 text-red-600" />
            <div>
              <p className="font-semibold">Research needs attention</p>
              <p className="mt-1 text-sm leading-6 text-red-800">{error}</p>
            </div>
          </div>
          <Button className="border-red-200 bg-white text-red-800 hover:bg-red-100" onClick={onRetry} variant="outline">
            <RefreshCw data-icon="inline-start" /> Try again
          </Button>
        </div>
      ) : null}

      {cancelled ? (
        <output className="mb-6 block rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm leading-6 text-amber-900">
          Research stopped. Partial results are shown below but were not saved.
        </output>
      ) : null}

      {report.warnings.length > 0 ? (
        <div className="mb-6 rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm leading-6 text-amber-900">
          {report.warnings.map((warning) => <p key={warning}>{warning}</p>)}
        </div>
      ) : null}

      <div className="space-y-5">
        <SectionCard active={activeSection === 'overview'} complete={sectionIsComplete('overview')} failed={sectionFailed('overview')} pending={sectionIsPending('overview')} retrying={activeSection === 'overview' && Boolean(statusMessage)} section="overview" sources={report.section_sources.overview}>
          {report.overview ? <p className="text-[1.02rem] leading-7 text-slate-700">{report.overview}</p> : sectionIsPending('overview') ? <LoadingSection active={activeSection === 'overview'} /> : <EmptySection />}
        </SectionCard>

        <SectionCard active={activeSection === 'key_people'} complete={sectionIsComplete('key_people')} failed={sectionFailed('key_people')} pending={sectionIsPending('key_people')} retrying={activeSection === 'key_people' && Boolean(statusMessage)} section="key_people" sources={report.section_sources.key_people}>
          {report.key_people?.length ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {report.key_people.map((person) => (
                <div className="rounded-xl border border-[var(--line)] bg-[var(--canvas)] p-4" key={`${person.name}-${person.title}`}>
                  <p className="font-semibold text-[var(--ink)]">{person.name}</p>
                  <p className="mt-1 text-sm leading-5 text-[var(--muted-ink)]">{person.title}</p>
                </div>
              ))}
            </div>
          ) : sectionIsPending('key_people') ? <LoadingSection active={activeSection === 'key_people'} /> : <EmptySection />}
        </SectionCard>

        <SectionCard active={activeSection === 'news'} complete={sectionIsComplete('news')} failed={sectionFailed('news')} pending={sectionIsPending('news')} retrying={activeSection === 'news' && Boolean(statusMessage)} section="news" sources={report.section_sources.news}>
          {report.news?.length ? (
            <div className="divide-y divide-[var(--line)]">
              {report.news.map((item) => (
                <div className="grid gap-2 py-4 first:pt-0 last:pb-0 sm:grid-cols-[110px_1fr]" key={`${item.headline}-${item.date}`}>
                  <p className="font-mono text-xs text-[var(--muted-ink)]">{item.date ?? 'Date unavailable'}</p>
                  <div>
                    <h3 className="font-semibold leading-6 text-[var(--ink)]">{item.headline}</h3>
                    <p className="mt-1 text-sm leading-6 text-slate-600">{item.summary}</p>
                  </div>
                </div>
              ))}
            </div>
          ) : sectionIsPending('news') ? <LoadingSection active={activeSection === 'news'} /> : <EmptySection message="No recent, verifiable company news was found." />}
        </SectionCard>

        <SectionCard active={activeSection === 'financials'} complete={sectionIsComplete('financials')} failed={sectionFailed('financials')} pending={sectionIsPending('financials')} retrying={activeSection === 'financials' && Boolean(statusMessage)} section="financials" sources={report.section_sources.financials}>
          {report.financials ? (
            <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {([
                ['Revenue', report.financials.revenue],
                ['Employees', report.financials.employee_count],
                ['Market cap', report.financials.market_cap],
                ['YoY growth', report.financials.yoy_growth],
              ] as const).map(([label, value]) => (
                <div className="rounded-xl border border-[var(--line)] bg-[var(--canvas)] p-4" key={label}>
                  <dt className="text-xs font-semibold uppercase tracking-[0.08em] text-[var(--muted-ink)]">{label}</dt>
                  <dd className={`mt-2 text-lg font-semibold tracking-[-0.025em] ${value ? 'text-[var(--ink)]' : 'text-slate-400'}`}>{value ?? 'Unavailable'}</dd>
                </div>
              ))}
            </dl>
          ) : sectionIsPending('financials') ? <LoadingSection active={activeSection === 'financials'} /> : <EmptySection message="Reliable financial metrics are not publicly available." />}
        </SectionCard>

        <SectionCard active={activeSection === 'risks'} complete={sectionIsComplete('risks')} failed={sectionFailed('risks')} pending={sectionIsPending('risks')} retrying={activeSection === 'risks' && Boolean(statusMessage)} section="risks" sources={report.section_sources.risks}>
          {report.risks?.length ? (
            <div className="space-y-3">
              {report.risks.map((risk) => (
                <div className="flex gap-3 rounded-xl border border-amber-200 bg-amber-50/70 p-4" key={risk.title}>
                  <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600" />
                  <div>
                    <h3 className="font-semibold text-amber-950">{risk.title}</h3>
                    <p className="mt-1 text-sm leading-6 text-amber-900/78">{risk.details}</p>
                  </div>
                </div>
              ))}
            </div>
          ) : sectionIsPending('risks') ? <LoadingSection active={activeSection === 'risks'} /> : <EmptySection message="No material, verifiable risk factors were found." />}
        </SectionCard>
      </div>
    </article>
  );
}

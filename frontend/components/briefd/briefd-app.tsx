'use client';

import { SyntheticEvent, useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, Building2, Command, LoaderCircle, Search, Sparkles } from 'lucide-react';

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Input } from '@/components/ui/input';
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar';
import { HistorySidebar } from '@/components/briefd/history-sidebar';
import { ReportView } from '@/components/briefd/report-view';
import { ApiError, deleteReport, getReport, listReports, streamResearch } from '@/lib/api';
import {
  createDraftReport,
  sectionOrder,
  type ReportSummary,
  type ResearchReport,
  type SectionKey,
  type Source,
  type StreamEvent,
} from '@/lib/briefd-types';

const stageLabels = ['Company', 'People', 'News', 'Numbers', 'Risks'];

type ModelContext = {
  registerTool: (
    tool: {
      name: string;
      title: string;
      description: string;
      inputSchema: Record<string, unknown>;
      annotations: { readOnlyHint: boolean; untrustedContentHint: boolean };
      execute: (input: unknown) => Promise<Record<string, unknown>>;
    },
    options: { signal: AbortSignal },
  ) => void | Promise<void>;
};

function companyValidationMessage(value: string): string | null {
  const name = value.trim();
  if (name.length < 2) return 'Enter a company name with at least two characters.';
  if (name.length > 120) return 'Keep the company name under 120 characters.';
  if (/^https?:\/\//i.test(name) || name.includes('@')) return 'Enter a company name, not a URL or email address.';
  if ((name.match(/[A-Za-z]/g) ?? []).length < 2) return 'Enter a recognizable company name.';
  return null;
}

function normalizeCompanyName(value: string): string {
  return value.trim().replace(/\s+/g, ' ').toLocaleLowerCase();
}

function eventMessage(event: StreamEvent): string {
  return typeof event.data.message === 'string'
    ? event.data.message
    : 'Research could not be completed. Please try again.';
}

export function BriefdApp() {
  const [companyName, setCompanyName] = useState('');
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [reportsLoading, setReportsLoading] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [report, setReport] = useState<ResearchReport | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<SectionKey | null>(null);
  const [completedSections, setCompletedSections] = useState<Set<SectionKey>>(new Set());
  const [failedSections, setFailedSections] = useState<Set<SectionKey>>(new Set());
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamStatus, setStreamStatus] = useState<string | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [cancelled, setCancelled] = useState(false);
  const [deleteCandidate, setDeleteCandidate] = useState<ReportSummary | null>(null);
  const [deleting, setDeleting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const requestRef = useRef<{ id: number; controller: AbortController; companyName: string } | null>(null);
  const requestSequence = useRef(0);

  const refreshHistory = useCallback(async () => {
    try {
      const history = await listReports();
      setReports(history);
      setHistoryError(null);
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : 'Report history is unavailable.');
    } finally {
      setReportsLoading(false);
    }
  }, []);

  useEffect(() => {
    void listReports()
      .then((history) => {
        setReports(history);
        setHistoryError(null);
      })
      .catch((error: unknown) => {
        setHistoryError(error instanceof Error ? error.message : 'Report history is unavailable.');
      })
      .finally(() => setReportsLoading(false));
  }, [refreshHistory]);

  useEffect(() => {
    const focusSearch = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', focusSearch);
    return () => window.removeEventListener('keydown', focusSearch);
  }, []);

  const cancelActiveRequest = useCallback((showMessage = true) => {
    const active = requestRef.current;
    if (!active) return;
    requestSequence.current += 1;
    active.controller.abort();
    requestRef.current = null;
    setIsStreaming(false);
    setActiveSection(null);
    setStreamStatus(null);
    if (showMessage) setCancelled(true);
  }, []);

  useEffect(() => () => cancelActiveRequest(false), [cancelActiveRequest]);

  const handleStreamEvent = useCallback((event: StreamEvent): ResearchReport | null => {
    if (event.event === 'section_started') {
      setActiveSection(event.data.section as SectionKey);
      setStreamStatus(null);
      return null;
    }

    if (event.event === 'section_progress') {
      setStreamStatus(null);
      return null;
    }

    if (event.event === 'section_retrying') {
      setActiveSection(event.data.section as SectionKey);
      setStreamStatus(eventMessage(event));
      return null;
    }

    if (event.event === 'section_completed') {
      const section = event.data.section as SectionKey;
      const data = event.data.data as ResearchReport[SectionKey];
      const sources = (event.data.sources ?? []) as Source[];
      setCompletedSections((current) => new Set(current).add(section));
      setStreamStatus(null);
      setReport((current) =>
        current
          ? {
              ...current,
              [section]: data,
              section_sources: { ...current.section_sources, [section]: sources },
            }
          : current,
      );
      return null;
    }

    if (event.event === 'section_failed') {
      const section = event.data.section as SectionKey;
      const message = eventMessage(event);
      setFailedSections((current) => new Set(current).add(section));
      setStreamStatus(null);
      setReport((current) =>
        current ? { ...current, warnings: [...current.warnings, message] } : current,
      );
      return null;
    }

    if (event.event === 'research_failed') {
      setStreamError(eventMessage(event));
      setIsStreaming(false);
      setActiveSection(null);
      setStreamStatus(null);
      return null;
    }

    if (event.event === 'research_completed') {
      const completedReport = event.data.report as ResearchReport;
      setReport(completedReport);
      setSelectedId(completedReport.id);
      setCompletedSections(new Set(sectionOrder));
      setIsStreaming(false);
      setActiveSection(null);
      setStreamStatus(null);
      return completedReport;
    }

    return null;
  }, []);

  const startResearch = useCallback(async (requestedName: string): Promise<ResearchReport | null> => {
    const name = requestedName.trim();
    const validationMessage = companyValidationMessage(name);
    if (validationMessage) {
      setSearchError(validationMessage);
      inputRef.current?.focus();
      return null;
    }

    if (
      requestRef.current &&
      normalizeCompanyName(requestRef.current.companyName) === normalizeCompanyName(name)
    ) {
      setSearchError(`Research is already running for ${name}.`);
      return null;
    }

    cancelActiveRequest(false);
    const requestId = ++requestSequence.current;
    const controller = new AbortController();
    requestRef.current = { id: requestId, controller, companyName: name };
    setCompanyName(name);
    setSearchError(null);
    setStreamError(null);
    setStreamStatus(null);
    setCancelled(false);
    setSelectedId(null);
    setReport(createDraftReport(name));
    setCompletedSections(new Set());
    setFailedSections(new Set());
    setActiveSection('overview');
    setIsStreaming(true);
    let completedReport: ResearchReport | null = null;

    try {
      await streamResearch(name, controller.signal, (event) => {
        if (requestRef.current?.id !== requestId) return;
        completedReport = handleStreamEvent(event) ?? completedReport;
      });
      if (requestRef.current?.id === requestId && !completedReport) {
        setIsStreaming(false);
        setActiveSection(null);
      }
    } catch (error) {
      if (controller.signal.aborted || requestRef.current?.id !== requestId) return null;
      setStreamError(
        error instanceof ApiError || error instanceof Error
          ? error.message
          : 'Research could not be completed. Please try again.',
      );
      setIsStreaming(false);
      setActiveSection(null);
      setStreamStatus(null);
    } finally {
      if (requestRef.current?.id === requestId) requestRef.current = null;
    }

    if (completedReport) await refreshHistory();
    return completedReport;
  }, [cancelActiveRequest, handleStreamEvent, refreshHistory]);

  useEffect(() => {
    const context = (document as Document & { modelContext?: ModelContext }).modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();

    try {
      void Promise.resolve(
        context.registerTool(
          {
            name: 'complete_company_research',
            title: 'Research a company',
            description: 'Research a named company and show the completed, source-backed briefing in Briefd.',
            inputSchema: {
              type: 'object',
              properties: { companyName: { type: 'string', minLength: 2, maxLength: 120 } },
              required: ['companyName'],
              additionalProperties: false,
            },
            annotations: { readOnlyHint: false, untrustedContentHint: true },
            async execute(input) {
              const company = (input as { companyName?: unknown }).companyName;
              if (typeof company !== 'string') throw new Error('companyName must be a string');
              const validationMessage = companyValidationMessage(company);
              if (validationMessage) throw new Error(validationMessage);
              const completed = await startResearch(company);
              if (!completed) throw new Error('Research did not complete. Review the visible error in Briefd.');
              return { reportId: completed.id, companyName: completed.company_name, status: 'complete' };
            },
          },
          { signal: lifecycle.signal },
        ),
      ).catch(() => undefined);
    } catch {
      // WebMCP is progressive enhancement; the visible workflow remains fully functional.
    }
    return () => lifecycle.abort();
  }, [startResearch]);

  const submitResearch = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    void startResearch(companyName);
  };

  const selectReport = async (summary: ReportSummary) => {
    cancelActiveRequest(false);
    setSelectedId(summary.id);
    setStreamError(null);
    setStreamStatus(null);
    setCancelled(false);
    setCompletedSections(new Set());
    setFailedSections(new Set());
    try {
      setReport(await getReport(summary.id));
    } catch (error) {
      setReport(null);
      setStreamError(error instanceof Error ? error.message : 'That report could not be loaded.');
    }
  };

  const confirmDelete = async () => {
    if (!deleteCandidate) return;
    setDeleting(true);
    try {
      await deleteReport(deleteCandidate.id);
      if (selectedId === deleteCandidate.id) {
        setReport(null);
        setSelectedId(null);
      }
      setDeleteCandidate(null);
      await refreshHistory();
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : 'The report could not be deleted.');
      setDeleteCandidate(null);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <SidebarProvider style={{ '--sidebar-width': '18rem' } as React.CSSProperties}>
      <HistorySidebar
        error={historyError}
        loading={reportsLoading}
        onDelete={setDeleteCandidate}
        onSelect={(summary) => void selectReport(summary)}
        reports={reports}
        selectedId={selectedId}
      />

      <SidebarInset className="min-w-0 bg-[var(--canvas)]">
        <header className="sticky top-0 z-20 border-b border-[var(--line)] bg-white/90 backdrop-blur-xl">
          <div className="mx-auto flex max-w-[1180px] items-start gap-3 px-4 py-3 sm:px-7">
            <SidebarTrigger className="mt-1 size-10 shrink-0 rounded-xl border border-[var(--line)] md:hidden" />
            <form className="flex min-w-0 flex-1 items-start gap-2" onSubmit={submitResearch}>
              <div className="min-w-0 flex-1">
                <div className="relative">
                  <Building2 className="absolute left-4 top-1/2 size-[18px] -translate-y-1/2 text-[var(--muted-ink)]" />
                  <Input
                    aria-describedby={searchError ? 'company-error' : undefined}
                    aria-invalid={Boolean(searchError)}
                    aria-label="Company name"
                    className="h-12 rounded-xl border-[var(--line-strong)] bg-white pl-11 pr-20 text-base shadow-[0_1px_2px_rgba(12,24,45,.04)] placeholder:text-slate-400 focus-visible:border-[var(--brand)] focus-visible:ring-[3px] focus-visible:ring-[var(--brand-soft)]"
                    onChange={(event) => {
                      setCompanyName(event.target.value);
                      if (searchError) setSearchError(null);
                    }}
                    placeholder="Research a company, e.g. Stripe"
                    ref={inputRef}
                    value={companyName}
                  />
                  <span className="pointer-events-none absolute right-3 top-1/2 hidden -translate-y-1/2 items-center gap-1 rounded-md border border-[var(--line)] bg-[var(--canvas)] px-2 py-1 text-[0.68rem] font-semibold text-[var(--muted-ink)] sm:flex">
                    <Command className="size-3" /> K
                  </span>
                </div>
                {searchError ? <p className="mt-1.5 text-sm text-red-600" id="company-error">{searchError}</p> : null}
              </div>
              <Button className="h-12 rounded-xl bg-[var(--brand)] px-4 text-white shadow-[0_10px_28px_rgba(34,78,211,.22)] hover:bg-[var(--brand-strong)] sm:px-5" size="lg" type="submit">
                {isStreaming ? (
                  <LoaderCircle className="animate-spin motion-reduce:animate-none" data-icon="inline-start" />
                ) : (
                  <Search data-icon="inline-start" />
                )}
                <span className="hidden sm:inline">{isStreaming ? 'Researching…' : 'Build briefing'}</span>
                <span className="sm:hidden">{isStreaming ? 'Working…' : 'Research'}</span>
              </Button>
            </form>
          </div>
        </header>

        <main className="mx-auto flex w-full max-w-[1180px] flex-1 flex-col px-4 py-6 sm:px-7 sm:py-9">
          {report ? (
            <ReportView
              activeSection={activeSection}
              cancelled={cancelled}
              completedSections={completedSections}
              error={streamError}
              failedSections={failedSections}
              isStreaming={isStreaming}
              onCancel={() => cancelActiveRequest(true)}
              onRetry={() => void startResearch(report.company_name)}
              report={report}
              statusMessage={streamStatus}
            />
          ) : (
            <Empty className="research-grid min-h-[580px] overflow-hidden border border-[var(--line)] bg-white p-0 shadow-[0_24px_70px_rgba(17,34,68,.06)]">
              <div className="relative z-10 flex w-full max-w-2xl flex-col items-center px-6 py-16 sm:px-10">
                {streamError ? (
                  <div className="mb-6 flex max-w-lg gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-left text-sm leading-6 text-red-900" role="alert">
                    <AlertTriangle className="mt-0.5 size-5 shrink-0 text-red-600" /> {streamError}
                  </div>
                ) : null}
                <EmptyHeader>
                  <EmptyMedia className="mb-5 size-14 rounded-2xl bg-[var(--brand-soft)] text-[var(--brand)]" variant="icon">
                    <Sparkles className="size-6" />
                  </EmptyMedia>
                  <EmptyTitle className="text-balance text-2xl font-semibold tracking-[-0.04em] text-[var(--ink)] sm:text-3xl">
                    Walk into the meeting already briefed.
                  </EmptyTitle>
                  <EmptyDescription className="mt-2 max-w-lg text-base leading-7 text-[var(--muted-ink)]">
                    Enter a company above. Briefd builds a structured sales briefing with Gemini while you watch.
                  </EmptyDescription>
                </EmptyHeader>
                <div className="mt-10 grid w-full grid-cols-5 items-start" aria-label="Briefing stages">
                  {stageLabels.map((stage, index) => (
                    <div className="relative flex min-w-0 flex-col items-center gap-2" key={stage}>
                      {index < stageLabels.length - 1 ? <span aria-hidden="true" className="absolute left-[50%] top-3 h-px w-full bg-[var(--line-strong)]" /> : null}
                      <span className="relative z-10 grid size-6 place-items-center rounded-full border border-[var(--line-strong)] bg-white font-mono text-[0.65rem] font-semibold text-[var(--brand)]">{index + 1}</span>
                      <span className="truncate text-[0.68rem] font-semibold uppercase tracking-[0.08em] text-[var(--muted-ink)] sm:text-xs">{stage}</span>
                    </div>
                  ))}
                </div>
              </div>
            </Empty>
          )}
        </main>
      </SidebarInset>

      <AlertDialog open={Boolean(deleteCandidate)} onOpenChange={(open) => !open && setDeleteCandidate(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this briefing?</AlertDialogTitle>
            <AlertDialogDescription>
              {deleteCandidate ? `${deleteCandidate.company_name} will be removed from your report history. This cannot be undone.` : ''}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Keep report</AlertDialogCancel>
            <AlertDialogAction className="bg-red-600 text-white hover:bg-red-700" disabled={deleting} onClick={() => void confirmDelete()}>
              {deleting ? 'Deleting…' : 'Delete report'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </SidebarProvider>
  );
}

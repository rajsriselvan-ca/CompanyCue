import { useCallback, useState } from 'react';

import { ConfirmDialog } from '@/components/ConfirmDialog';
import { EmptyState } from '@/components/EmptyState';
import { HistorySidebar } from '@/components/HistorySidebar';
import { ReportView } from '@/components/ReportView';
import { SearchBar } from '@/components/SearchBar';
import { Button } from '@/components/ui/primitives';
import { useReports } from '@/hooks/useReports';
import { useResearchStream } from '@/hooks/useResearchStream';
import { getReport } from '@/lib/api';
import type { ReportSummary, ResearchReport } from '@/lib/types';

export default function App() {
  const history = useReports();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [deleteCandidate, setDeleteCandidate] = useState<ReportSummary | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const onCompleted = useCallback(
    (report: ResearchReport) => {
      // Show it in the sidebar straight away, then reconcile with the server.
      history.addOptimistic({
        id: report.id,
        company_name: report.company_name,
        created_at: report.created_at,
      });
      void history.refresh();
    },
    [history],
  );

  const research = useResearchStream(onCompleted);
  const { state } = research;

  const startResearch = useCallback(
    (companyName: string) => {
      setLoadError(null);
      setSidebarOpen(false);
      research.start(companyName);
    },
    [research],
  );

  const openReport = useCallback(
    async (summary: ReportSummary) => {
      setLoadError(null);
      setSidebarOpen(false);
      try {
        research.showReport(await getReport(summary.id));
      } catch (error) {
        setLoadError(error instanceof Error ? error.message : 'That briefing could not be loaded.');
      }
    },
    [research],
  );

  const confirmDelete = useCallback(async () => {
    if (!deleteCandidate) return;
    setDeleting(true);
    try {
      await history.remove(deleteCandidate.id);
      if (state.savedSummary?.id === deleteCandidate.id) research.reset();
      setDeleteCandidate(null);
    } catch {
      setDeleteCandidate(null); // useReports already surfaced the message.
    } finally {
      setDeleting(false);
    }
  }, [deleteCandidate, history, research, state.savedSummary]);

  const hasReport = state.phase !== 'idle';

  return (
    <div className="flex min-h-screen">
      <aside
        className={`fixed inset-y-0 left-0 z-30 w-72 transition-transform md:static md:translate-x-0 ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <HistorySidebar
          error={history.error}
          loading={history.loading}
          onDelete={setDeleteCandidate}
          onSelect={(summary) => void openReport(summary)}
          reports={history.reports}
          selectedId={state.savedSummary?.id ?? null}
        />
      </aside>

      {sidebarOpen ? (
        <button
          aria-label="Close report history"
          className="fixed inset-0 z-20 bg-ink/20 md:hidden"
          onClick={() => setSidebarOpen(false)}
          type="button"
        />
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 border-b border-line bg-canvas/90 backdrop-blur">
          <div className="mx-auto flex max-w-4xl items-start gap-2 px-4 py-3 sm:px-6">
            <Button
              aria-label="Open report history"
              className="h-11 px-3 md:hidden"
              onClick={() => setSidebarOpen(true)}
              variant="secondary"
            >
              ☰
            </Button>
            <SearchBar
              onCancel={research.cancel}
              onSubmit={startResearch}
              streaming={research.streaming}
            />
          </div>
        </header>

        <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-6 sm:px-6 sm:py-8">
          {hasReport ? (
            <ReportView onRetry={() => startResearch(state.companyName)} state={state} />
          ) : (
            <EmptyState error={loadError} onExample={startResearch} />
          )}
        </main>
      </div>

      <ConfirmDialog
        busy={deleting}
        confirmLabel="Delete briefing"
        description={
          deleteCandidate
            ? `The ${deleteCandidate.company_name} briefing will be removed from your history. This cannot be undone.`
            : ''
        }
        onCancel={() => setDeleteCandidate(null)}
        onConfirm={() => void confirmDelete()}
        open={Boolean(deleteCandidate)}
        title="Delete this briefing?"
      />
    </div>
  );
}

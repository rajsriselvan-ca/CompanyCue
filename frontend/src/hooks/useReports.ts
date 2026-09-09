import { useCallback, useEffect, useRef, useState } from 'react';

import { deleteReport, listReports } from '@/lib/api';
import type { ReportSummary } from '@/lib/types';

export interface UseReports {
  reports: ReportSummary[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  remove: (reportId: string) => Promise<void>;
  addOptimistic: (summary: ReportSummary) => void;
}

/** Report history: load once, refresh after a run, delete with rollback. */
export function useReports(): UseReports {
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    const controller = new AbortController();
    listReports(controller.signal)
      .then((history) => {
        if (!mountedRef.current) return;
        setReports(history);
        setError(null);
      })
      .catch((cause: unknown) => {
        if (!mountedRef.current || controller.signal.aborted) return;
        setError(cause instanceof Error ? cause.message : 'Report history is unavailable.');
      })
      .finally(() => {
        if (mountedRef.current) setLoading(false);
      });
    return () => {
      mountedRef.current = false;
      controller.abort();
    };
  }, []);

  const refresh = useCallback(async () => {
    try {
      const history = await listReports();
      if (!mountedRef.current) return;
      setReports(history);
      setError(null);
    } catch (cause) {
      if (!mountedRef.current) return;
      setError(cause instanceof Error ? cause.message : 'Report history is unavailable.');
    }
  }, []);

  const remove = useCallback(async (reportId: string) => {
    const previous = reports;
    setReports((current) => current.filter((report) => report.id !== reportId));
    try {
      await deleteReport(reportId);
    } catch (cause) {
      if (!mountedRef.current) return;
      setReports(previous); // Put it back rather than lying about the delete.
      setError(cause instanceof Error ? cause.message : 'That report could not be deleted.');
      throw cause;
    }
  }, [reports]);

  const addOptimistic = useCallback((summary: ReportSummary) => {
    setReports((current) =>
      current.some((report) => report.id === summary.id) ? current : [summary, ...current],
    );
  }, []);

  return { reports, loading, error, refresh, remove, addOptimistic };
}

import { useCallback, useEffect, useReducer, useRef } from 'react';

import { ApiError, streamResearch } from '@/lib/api';
import {
  initialStreamState,
  isStreaming,
  streamReducer,
  type StreamState,
} from '@/lib/streamState';
import type { ResearchReport } from '@/lib/types';

export interface UseResearchStream {
  state: StreamState;
  streaming: boolean;
  start: (companyName: string) => void;
  cancel: () => void;
  showReport: (report: ResearchReport) => void;
  reset: () => void;
}

/**
 * Owns one research stream at a time.
 *
 * Three things this has to get right, all of which the brief calls out:
 *
 * - **Rapid successive searches.** Each run gets a monotonic id. Starting a new
 *   one aborts the old fetch *and* bumps the id, so a late event from the
 *   abandoned stream is dropped instead of writing into the new run's state.
 * - **Unmount during an active stream.** The cleanup aborts the controller,
 *   which cancels the fetch body; the `mounted` ref stops any in-flight
 *   iteration from dispatching into an unmounted component.
 * - **A stream that ends without a terminal event.** The loop falls through to
 *   `streamEndedEarly`, so a dropped connection surfaces as an error the user
 *   can retry rather than a spinner that never stops.
 */
export function useResearchStream(
  onCompleted?: (report: ResearchReport) => void,
): UseResearchStream {
  const [state, dispatch] = useReducer(streamReducer, initialStreamState);

  const controllerRef = useRef<AbortController | null>(null);
  const runIdRef = useRef(0);
  const mountedRef = useRef(true);
  // Kept in a ref so a changing callback identity does not re-create `start`.
  const onCompletedRef = useRef(onCompleted);
  onCompletedRef.current = onCompleted;

  const abortActive = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      abortActive();
    };
  }, [abortActive]);

  const start = useCallback(
    (companyName: string) => {
      const name = companyName.trim().replace(/\s+/g, ' ');
      if (!name) return;

      abortActive();
      const runId = ++runIdRef.current;
      const controller = new AbortController();
      controllerRef.current = controller;

      const isCurrent = () => mountedRef.current && runIdRef.current === runId;

      dispatch({ type: 'start', companyName: name });

      void (async () => {
        let sawTerminalEvent = false;
        try {
          for await (const event of streamResearch(name, controller.signal)) {
            if (!isCurrent()) return;
            if (event.event === 'research_completed' || event.event === 'research_failed') {
              sawTerminalEvent = true;
            }
            dispatch({ type: 'event', event });
            if (event.event === 'research_completed') {
              const report = event.data.report as ResearchReport | undefined;
              if (report) onCompletedRef.current?.(report);
            }
          }
          if (isCurrent() && !sawTerminalEvent) dispatch({ type: 'streamEndedEarly' });
        } catch (error) {
          if (controller.signal.aborted || !isCurrent()) return;
          if (error instanceof ApiError) {
            dispatch({
              type: 'transportError',
              message: error.message,
              // 409 means a duplicate run is already in flight; retrying
              // immediately would just conflict again.
              retryable: error.status !== 409,
            });
            return;
          }
          dispatch({
            type: 'transportError',
            message: 'Research could not be completed. Please try again.',
          });
        } finally {
          if (controllerRef.current === controller) controllerRef.current = null;
        }
      })();
    },
    [abortActive],
  );

  const cancel = useCallback(() => {
    abortActive();
    dispatch({ type: 'cancelled' });
  }, [abortActive]);

  const showReport = useCallback(
    (report: ResearchReport) => {
      // Viewing history stops the live run; two briefings on one screen would
      // be worse than either.
      abortActive();
      runIdRef.current += 1;
      dispatch({ type: 'loadReport', report });
    },
    [abortActive],
  );

  const reset = useCallback(() => {
    abortActive();
    runIdRef.current += 1;
    dispatch({ type: 'reset' });
  }, [abortActive]);

  return { state, streaming: isStreaming(state.phase), start, cancel, showReport, reset };
}

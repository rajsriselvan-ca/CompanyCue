import { readSSE } from '@/lib/sse';
import type { ReportSummary, ResearchEvent, ResearchReport } from '@/lib/types';

// Empty by default: requests go to `/api/...` on the same origin, which the
// Vite dev server proxies to the backend. Set VITE_API_URL to point a built
// frontend at a backend on another host.
const API_URL = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

const OFFLINE_MESSAGE =
  'The CompanyCue API is not responding. Start the backend and try again.';

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === 'string' && payload.detail.trim()) return payload.detail;
    if (Array.isArray(payload.detail)) {
      const first = payload.detail[0] as { msg?: string } | undefined;
      if (first?.msg) return first.msg.replace(/^Value error, /, '');
    }
  } catch {
    // Falls through to a status-based message; response internals never
    // reach the user.
  }
  return response.status >= 500
    ? 'CompanyCue could not reach the research service. Please try again.'
    : 'That request could not be completed. Please check it and try again.';
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api${path}`, init);
  } catch (error) {
    if (init?.signal?.aborted) throw error;
    throw new ApiError(OFFLINE_MESSAGE, 0);
  }
  if (!response.ok) throw new ApiError(await readErrorMessage(response), response.status);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function listReports(signal?: AbortSignal): Promise<ReportSummary[]> {
  return request('/reports', { signal });
}

export function getReport(reportId: string, signal?: AbortSignal): Promise<ResearchReport> {
  return request(`/reports/${reportId}`, { signal });
}

export function deleteReport(reportId: string): Promise<void> {
  return request(`/reports/${reportId}`, { method: 'DELETE' });
}

/**
 * POST /api/research and yield each research event as the server emits it.
 *
 * Aborting the signal cancels the fetch, which closes the TCP connection; the
 * backend sees the disconnect and cancels the agent, so a cancelled search
 * stops costing API quota immediately.
 */
export async function* streamResearch(
  companyName: string,
  signal: AbortSignal,
): AsyncGenerator<ResearchEvent> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/research`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ company_name: companyName }),
      signal,
    });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new ApiError(OFFLINE_MESSAGE, 0);
  }

  if (!response.ok) throw new ApiError(await readErrorMessage(response), response.status);
  if (!response.body) {
    throw new ApiError('The research stream could not be opened. Please try again.', 502);
  }

  for await (const frame of readSSE(response.body, signal)) {
    if (!frame.data) continue;
    let data: Record<string, unknown>;
    try {
      data = JSON.parse(frame.data) as Record<string, unknown>;
    } catch {
      // One malformed frame should not end an otherwise healthy stream.
      continue;
    }
    yield { id: frame.id, event: frame.event, data };
  }
}

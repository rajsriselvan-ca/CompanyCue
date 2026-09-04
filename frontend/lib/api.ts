import type { ReportSummary, ResearchReport, StreamEvent } from '@/lib/briefd-types';
import { readSSEStream } from '@/lib/sse';

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string | Array<{ msg?: string }> };
    if (typeof payload.detail === 'string') return payload.detail;
    if (Array.isArray(payload.detail)) {
      return payload.detail[0]?.msg?.replace(/^Value error, /, '') ?? 'Check the information and try again.';
    }
  } catch {
    // The fallback below is intentionally user-facing and contains no response internals.
  }
  return response.status >= 500
    ? 'Briefd could not reach the research service. Please try again.'
    : 'The request could not be completed. Please check it and try again.';
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new ApiError('The Briefd API is offline. Start the backend and try again.', 0);
  }

  if (!response.ok) throw new ApiError(await errorMessage(response), response.status);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function listReports(): Promise<ReportSummary[]> {
  return request('/api/reports');
}

export function getReport(reportId: string): Promise<ResearchReport> {
  return request(`/api/reports/${reportId}`);
}

export function deleteReport(reportId: string): Promise<void> {
  return request(`/api/reports/${reportId}`, { method: 'DELETE' });
}

export async function streamResearch(
  companyName: string,
  signal: AbortSignal,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/research`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ company_name: companyName }),
      signal,
    });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new ApiError('The Briefd API is offline. Start the backend and try again.', 0);
  }

  if (!response.ok) throw new ApiError(await errorMessage(response), response.status);
  if (!response.body) throw new ApiError('The research stream could not be opened. Please try again.', 502);

  for await (const event of readSSEStream(response.body)) onEvent(event);
}

import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useResearchStream } from '@/hooks/useResearchStream';

/**
 * Drives the hook through a fake `fetch` that returns a controllable SSE body,
 * so the awkward cases — a second search while the first is mid-stream, an
 * unmount during a stream, a connection that just stops — are reproducible.
 */
class FakeStream {
  private controller!: ReadableStreamDefaultController<Uint8Array>;
  readonly body: ReadableStream<Uint8Array>;
  cancelled = false;

  constructor() {
    this.body = new ReadableStream<Uint8Array>({
      start: (controller) => {
        this.controller = controller;
      },
    });
  }

  emit(event: string, data: unknown) {
    if (this.cancelled) return;
    this.controller.enqueue(
      new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`),
    );
  }

  /** What a real `fetch` does to its body when the signal aborts. */
  abort() {
    if (this.cancelled) return;
    this.cancelled = true;
    this.controller.error(new DOMException('The user aborted a request.', 'AbortError'));
  }

  end() {
    if (this.cancelled) return;
    this.controller.close();
  }
}

let streams: FakeStream[] = [];
const fetchMock = vi.fn();

beforeEach(() => {
  streams = [];
  fetchMock.mockReset();
  fetchMock.mockImplementation((_url: string, init: RequestInit) => {
    const stream = new FakeStream();
    streams.push(stream);
    init.signal?.addEventListener('abort', () => stream.abort());
    return Promise.resolve(
      new Response(stream.body, {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      }),
    );
  });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const report = {
  id: 'r1',
  company_name: 'Acme Corp',
  created_at: '2026-09-09T10:00:00Z',
  overview: 'Acme makes widgets.',
  key_people: [],
  news: [],
  financials: { revenue: null, employee_count: null, market_cap: null, yoy_growth: null },
  risks: [],
  section_sources: {},
  warnings: [],
};

describe('useResearchStream', () => {
  it('streams events into state and reports completion once', async () => {
    const onCompleted = vi.fn();
    const { result } = renderHook(() => useResearchStream(onCompleted));

    act(() => result.current.start('Acme Corp'));
    await waitFor(() => expect(streams).toHaveLength(1));

    act(() => {
      streams[0]!.emit('research_started', { company_name: 'Acme Corp' });
      streams[0]!.emit('section_completed', { section: 'overview', data: 'Acme.', sources: [] });
    });
    await waitFor(() => expect(result.current.state.sections.overview.status).toBe('complete'));
    expect(result.current.streaming).toBe(true);

    act(() => {
      streams[0]!.emit('research_completed', { report });
      streams[0]!.end();
    });

    await waitFor(() => expect(result.current.state.phase).toBe('complete'));
    expect(onCompleted).toHaveBeenCalledTimes(1);
    expect(result.current.streaming).toBe(false);
  });

  it('a rapid second search aborts the first and ignores its late events', async () => {
    const { result } = renderHook(() => useResearchStream());

    act(() => result.current.start('Acme Corp'));
    await waitFor(() => expect(streams).toHaveLength(1));

    act(() => result.current.start('Globex'));
    await waitFor(() => expect(streams).toHaveLength(2));

    // The abandoned stream was cancelled, so the backend stops its agent.
    await waitFor(() => expect(streams[0]!.cancelled).toBe(true));

    // A late event from the abandoned run must not leak into the new one.
    act(() => {
      streams[0]!.emit('section_completed', { section: 'risks', data: [{ title: 'stale' }], sources: [] });
      streams[1]!.emit('research_started', { company_name: 'Globex' });
    });

    await waitFor(() => expect(result.current.state.companyName).toBe('Globex'));
    expect(result.current.state.sections.risks.status).toBe('pending');
  });

  it('cancelling stops the stream and says so', async () => {
    const { result } = renderHook(() => useResearchStream());

    act(() => result.current.start('Acme Corp'));
    await waitFor(() => expect(streams).toHaveLength(1));

    act(() => result.current.cancel());

    await waitFor(() => expect(result.current.state.phase).toBe('cancelled'));
    await waitFor(() => expect(streams[0]!.cancelled).toBe(true));
    expect(result.current.streaming).toBe(false);
  });

  it('unmounting during a live stream aborts it without warning', async () => {
    const { result, unmount } = renderHook(() => useResearchStream());

    act(() => result.current.start('Acme Corp'));
    await waitFor(() => expect(streams).toHaveLength(1));

    unmount();

    await waitFor(() => expect(streams[0]!.cancelled).toBe(true));
    // Emitting after unmount must not throw or update anything.
    expect(() => streams[0]!.end()).not.toThrow();
  });

  it('a connection that closes without a terminal event becomes an error', async () => {
    const { result } = renderHook(() => useResearchStream());

    act(() => result.current.start('Acme Corp'));
    await waitFor(() => expect(streams).toHaveLength(1));

    act(() => {
      streams[0]!.emit('stage', { stage: 'searching' });
      streams[0]!.end();
    });

    await waitFor(() => expect(result.current.state.phase).toBe('error'));
    expect(result.current.state.error?.retryable).toBe(true);
  });

  it('an unreachable backend produces a readable message, not a stack trace', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    const { result } = renderHook(() => useResearchStream());

    act(() => result.current.start('Acme Corp'));

    await waitFor(() => expect(result.current.state.phase).toBe('error'));
    expect(result.current.state.error?.message).toMatch(/not responding/i);
  });

  it('a duplicate run (409) is reported as not worth retrying', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: 'A briefing for Acme Corp is already being generated.' }), {
        status: 409,
        headers: { 'content-type': 'application/json' },
      }),
    );
    const { result } = renderHook(() => useResearchStream());

    act(() => result.current.start('Acme Corp'));

    await waitFor(() => expect(result.current.state.phase).toBe('error'));
    expect(result.current.state.error?.retryable).toBe(false);
    expect(result.current.state.error?.message).toMatch(/already being generated/);
  });

  it('opening a saved report abandons the live run', async () => {
    const { result } = renderHook(() => useResearchStream());

    act(() => result.current.start('Acme Corp'));
    await waitFor(() => expect(streams).toHaveLength(1));

    act(() => result.current.showReport(report));

    await waitFor(() => expect(result.current.state.phase).toBe('complete'));
    await waitFor(() => expect(streams[0]!.cancelled).toBe(true));
  });
});

import { describe, expect, it } from 'vitest';

import {
  initialStreamState,
  streamReducer,
  type StreamAction,
  type StreamState,
} from '@/lib/streamState';
import type { ResearchReport } from '@/lib/types';

const event = (name: string, data: Record<string, unknown>): StreamAction => ({
  type: 'event',
  event: { event: name, data },
});

function run(actions: StreamAction[], from: StreamState = initialStreamState): StreamState {
  return actions.reduce(streamReducer, from);
}

const started = [
  { type: 'start', companyName: 'Acme Corp' } as StreamAction,
  event('research_started', { company_name: 'Acme Corp' }),
];

describe('streamReducer', () => {
  it('moves through planning, searching and writing', () => {
    const state = run([
      ...started,
      event('stage', { stage: 'planning', message: 'Planning research' }),
    ]);
    expect(state.phase).toBe('planning');

    const searching = streamReducer(state, event('stage', { stage: 'searching' }));
    expect(searching.phase).toBe('searching');

    const writing = streamReducer(
      searching,
      event('stage', { stage: 'synthesizing', evidence_count: 12 }),
    );
    expect(writing.phase).toBe('writing');
    expect(writing.evidenceCount).toBe(12);
  });

  it('records a search and then resolves it with its result', () => {
    const state = run([
      ...started,
      event('tool_call', { id: 'c1', tool: 'news_search', query: 'acme funding' }),
      event('tool_result', { id: 'c1', result_count: 4, new_sources: 3, elapsed_ms: 210 }),
    ]);

    expect(state.activity).toEqual([
      {
        id: 'c1',
        tool: 'news_search',
        query: 'acme funding',
        status: 'done',
        resultCount: 4,
        newSources: 3,
        elapsedMs: 210,
        message: null,
      },
    ]);
  });

  it('marks a failed search without dropping it from the log', () => {
    const state = run([
      ...started,
      event('tool_call', { id: 'c1', tool: 'web_search', query: 'acme' }),
      event('tool_result', { id: 'c1', result_count: 0, error: 'Search failed.' }),
    ]);

    expect(state.activity[0]!.status).toBe('failed');
    expect(state.activity[0]!.message).toBe('Search failed.');
  });

  it('exposes partial section content while it streams', () => {
    const state = run([
      ...started,
      event('section_started', { section: 'key_people' }),
      event('section_delta', { section: 'key_people', partial: { key_people: [{ name: 'Ada' }] } }),
      event('section_delta', {
        section: 'key_people',
        partial: { key_people: [{ name: 'Ada', title: 'CEO' }, { name: 'Grace' }] },
      }),
    ]);

    const section = state.sections.key_people;
    expect(section.status).toBe('streaming');
    expect(section.partial).toEqual({
      key_people: [{ name: 'Ada', title: 'CEO' }, { name: 'Grace' }],
    });
    expect(section.data).toBeNull();
  });

  it('replaces the partial with validated data on completion', () => {
    const state = run([
      ...started,
      event('section_started', { section: 'overview' }),
      event('section_delta', { section: 'overview', partial: { overview: 'Acme mak' } }),
      event('section_completed', {
        section: 'overview',
        data: 'Acme makes widgets.',
        sources: [{ title: 'Acme', url: 'https://acme.com' }],
      }),
    ]);

    expect(state.sections.overview).toMatchObject({
      status: 'complete',
      data: 'Acme makes widgets.',
      partial: null,
    });
    expect(state.sections.overview.sources).toHaveLength(1);
  });

  it('fails one section without touching the others', () => {
    const state = run([
      ...started,
      event('section_completed', { section: 'overview', data: 'Acme.', sources: [] }),
      event('section_failed', { section: 'risks', message: 'Risk factors is unavailable.' }),
    ]);

    expect(state.sections.risks.status).toBe('failed');
    expect(state.sections.overview.status).toBe('complete');
    expect(state.warnings).toEqual(['Risk factors is unavailable.']);
    expect(state.phase).not.toBe('error');
  });

  it('surfaces a backend failure as a retryable error', () => {
    const state = run([
      ...started,
      event('research_failed', {
        code: 'rate_limited',
        message: 'Rate limited. Try again shortly.',
        retryable: true,
      }),
    ]);

    expect(state.phase).toBe('error');
    expect(state.error).toEqual({
      message: 'Rate limited. Try again shortly.',
      retryable: true,
    });
  });

  it('marks a non-retryable failure as such', () => {
    const state = run([
      ...started,
      event('research_failed', { code: 'no_evidence', message: 'Nothing found.', retryable: false }),
    ]);
    expect(state.error?.retryable).toBe(false);
  });

  it('reports a stream that ends without a terminal event', () => {
    const state = run([...started, { type: 'streamEndedEarly' }]);

    expect(state.phase).toBe('error');
    expect(state.error?.message).toMatch(/dropped/i);
  });

  it('does not overwrite a finished run when the stream then closes', () => {
    const completed = run([...started, event('research_completed', { report: report() })]);
    expect(streamReducer(completed, { type: 'streamEndedEarly' })).toBe(completed);
    expect(streamReducer(completed, { type: 'cancelled' })).toBe(completed);
  });

  it('keeps live sources when the saved report does not carry them', () => {
    const state = run([
      ...started,
      event('section_completed', {
        section: 'overview',
        data: 'Acme.',
        sources: [{ title: 'Acme', url: 'https://acme.com' }],
      }),
      event('research_completed', { report: { ...report(), section_sources: {} } }),
    ]);

    expect(state.phase).toBe('complete');
    expect(state.sections.overview.sources).toHaveLength(1);
  });

  it('renders a saved report through the same section shape as a live run', () => {
    const state = streamReducer(initialStreamState, {
      type: 'loadReport',
      report: { ...report(), risks: null },
    });

    expect(state.phase).toBe('complete');
    expect(state.sections.overview.status).toBe('complete');
    expect(state.sections.risks.status).toBe('failed');
    expect(state.savedSummary?.id).toBe('r1');
  });

  it('ignores events for unknown sections and unknown event names', () => {
    const before = run(started);
    expect(streamReducer(before, event('section_delta', { section: 'nope' }))).toBe(before);
    expect(streamReducer(before, event('some_future_event', {}))).toBe(before);
  });
});

function report(): ResearchReport {
  return {
    id: 'r1',
    company_name: 'Acme Corp',
    created_at: '2026-09-09T10:00:00Z',
    overview: 'Acme makes widgets.',
    key_people: [{ name: 'Ada', title: 'CEO' }],
    news: [],
    financials: { revenue: '$1B', employee_count: null, market_cap: null, yoy_growth: null },
    risks: [{ title: 'Regulation', details: 'Under review.' }],
    section_sources: { overview: [{ title: 'Acme', url: 'https://acme.com' }] },
    warnings: [],
  };
}

import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ReportView } from '@/components/ReportView';
import { validateCompanyName } from '@/components/SearchBar';
import { initialStreamState, streamReducer, type StreamAction, type StreamState } from '@/lib/streamState';

const event = (name: string, data: Record<string, unknown>): StreamAction => ({
  type: 'event',
  event: { event: name, data },
});

function stateAfter(actions: StreamAction[]): StreamState {
  return [
    { type: 'start', companyName: 'Acme Corp' } as StreamAction,
    ...actions,
  ].reduce(streamReducer, initialStreamState);
}

function show(state: StreamState) {
  return render(<ReportView onRetry={vi.fn()} state={state} />);
}

describe('ReportView', () => {
  it('renders a half-streamed section instead of waiting for it to finish', () => {
    show(
      stateAfter([
        event('stage', { stage: 'synthesizing' }),
        event('section_started', { section: 'key_people' }),
        event('section_delta', {
          section: 'key_people',
          partial: { key_people: [{ name: 'Dana Whitfield', title: 'Chief Executive Officer' }] },
        }),
      ]),
    );

    // The one person written so far is on screen, mid-stream.
    expect(screen.getByText('Dana Whitfield')).toBeInTheDocument();
    expect(screen.getByText('Chief Executive Officer')).toBeInTheDocument();
    // And the section is announced as busy for assistive technology.
    expect(screen.getByLabelText('Key people')).toHaveAttribute('aria-busy', 'true');
  });

  it('shows overview prose as it arrives, with a streaming caret', () => {
    const { container } = show(
      stateAfter([
        event('section_started', { section: 'overview' }),
        event('section_delta', { section: 'overview', partial: { overview: 'Acme makes wid' } }),
      ]),
    );

    expect(screen.getByText('Acme makes wid')).toBeInTheDocument();
    expect(container.querySelector('.streaming-caret')).not.toBeNull();
  });

  it('shows progress while streaming and the source count when done', () => {
    show(
      stateAfter([
        event('stage', { stage: 'searching', message: 'Searching the web' }),
        event('tool_call', { id: 'c1', tool: 'news_search', query: 'acme funding' }),
        event('tool_result', { id: 'c1', result_count: 3, new_sources: 3, elapsed_ms: 180 }),
      ]),
    );

    expect(screen.getByRole('status')).toHaveTextContent('Searching the web');
    expect(screen.getByText('acme funding')).toBeInTheDocument();
    expect(screen.getByText(/3 results/)).toBeInTheDocument();
  });

  it('explains a failed section rather than leaving it blank', () => {
    show(
      stateAfter([
        event('section_failed', {
          section: 'risks',
          message: 'Risk factors is unavailable: the provider timed out.',
        }),
      ]),
    );

    const section = screen.getByLabelText('Risk factors');
    expect(within(section).getByText(/the provider timed out/)).toBeInTheDocument();
    expect(screen.getByText('unavailable')).toBeInTheDocument();
  });

  it('says "not disclosed" instead of inventing a missing financial figure', () => {
    show(
      stateAfter([
        event('section_completed', {
          section: 'financials',
          data: {
            revenue: '$4.2B (FY2025)',
            employee_count: null,
            market_cap: null,
            yoy_growth: '24%',
          },
          sources: [],
        }),
      ]),
    );

    const section = screen.getByLabelText('Financial highlights');
    expect(within(section).getByText('$4.2B (FY2025)')).toBeInTheDocument();
    expect(within(section).getAllByText('Not disclosed')).toHaveLength(2);
  });

  it('tells the user what an empty section means rather than showing nothing', () => {
    show(stateAfter([event('section_completed', { section: 'news', data: [], sources: [] })]));

    expect(screen.getByText(/No material news from the past year/)).toBeInTheDocument();
  });

  it('links the sources a section was written from', () => {
    show(
      stateAfter([
        event('section_completed', {
          section: 'overview',
          data: 'Acme makes widgets.',
          sources: [{ title: 'Acme home', url: 'https://www.acme.com/about' }],
        }),
      ]),
    );

    const link = screen.getByRole('link', { name: 'acme.com' });
    expect(link).toHaveAttribute('href', 'https://www.acme.com/about');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noreferrer'));
  });

  it('surfaces a stream error with a retry affordance', () => {
    show(
      stateAfter([
        event('research_failed', { message: 'Rate limited. Try again shortly.', retryable: true }),
      ]),
    );

    expect(screen.getByRole('alert')).toHaveTextContent('Rate limited. Try again shortly.');
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('offers no retry for a failure that retrying cannot fix', () => {
    show(
      stateAfter([
        event('research_failed', { message: 'No usable web results.', retryable: false }),
      ]),
    );

    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument();
  });
});

describe('validateCompanyName', () => {
  it.each(['Stripe', 'JPMorgan Chase & Co.', `Acme ${'Holdings '.repeat(12)}`.slice(0, 120), '3M'])(
    'accepts %s',
    (value) => {
      expect(validateCompanyName(value)).toBeNull();
    },
  );

  it.each([
    ['', /at least two characters/],
    [' a ', /at least two characters/],
    ['x'.repeat(121), /under 120 characters/],
    ['https://stripe.com', /not a URL/],
    ['sales@stripe.com', /not a URL/],
    ['!!!!', /recognizable/],
    ['aaaaa', /recognizable/],
  ])('rejects %s', (value, expected) => {
    expect(validateCompanyName(value)).toMatch(expected);
  });
});

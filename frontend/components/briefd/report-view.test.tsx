import { render, screen } from '@testing-library/react';

import { ReportView } from '@/components/briefd/report-view';
import type { ResearchReport } from '@/lib/briefd-types';

const report: ResearchReport = {
  id: 'db5c3bbd-7c85-4b86-97ff-dd879ad7a002',
  company_name: 'Verified Co',
  created_at: '2026-09-03T10:00:00Z',
  overview: 'Verified Co makes research software for sales teams.',
  key_people: [],
  news: [],
  financials: {
    revenue: null,
    employee_count: '120 (2026)',
    market_cap: null,
    yoy_growth: null,
  },
  risks: null,
  section_sources: {
    overview: [{ title: 'Verified Co', url: 'https://example.com/verified' }],
  },
  warnings: [],
};

describe('ReportView', () => {
  it('renders all five sections and marks unavailable metrics honestly', () => {
    render(
      <ReportView
        activeSection={null}
        cancelled={false}
        completedSections={new Set()}
        error={null}
        failedSections={new Set()}
        isStreaming={false}
        onCancel={jest.fn()}
        onRetry={jest.fn()}
        report={report}
        statusMessage={null}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Verified Co' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Company overview' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Key people' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Recent news' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Financial highlights' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Risk factors' })).toBeInTheDocument();
    expect(screen.getAllByText('Unavailable')).toHaveLength(3);
    expect(screen.getByRole('link', { name: /Verified Co/ })).toHaveAttribute('href', 'https://example.com/verified');
  });

  it('keeps partial results visible with a human-readable stream error', () => {
    render(
      <ReportView
        activeSection={null}
        cancelled={false}
        completedSections={new Set(['overview'])}
        error="The research service is temporarily unavailable."
        failedSections={new Set(['key_people'])}
        isStreaming={false}
        onCancel={jest.fn()}
        onRetry={jest.fn()}
        report={{ ...report, id: 'draft', key_people: null, news: null, financials: null }}
        statusMessage={null}
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('temporarily unavailable');
    expect(screen.getByText('Verified Co makes research software for sales teams.')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeEnabled();
  });

  it('shows compact loaders without an error while sections are streaming', () => {
    render(
      <ReportView
        activeSection="overview"
        cancelled={false}
        completedSections={new Set()}
        error="A stale error that must stay hidden while streaming."
        failedSections={new Set()}
        isStreaming
        onCancel={jest.fn()}
        onRetry={jest.fn()}
        report={{
          ...report,
          id: 'draft',
          overview: null,
          key_people: null,
          news: null,
          financials: null,
          risks: null,
        }}
        statusMessage="Free-tier capacity is busy. Briefd is waiting and will retry automatically."
      />,
    );

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByText('Waiting')).toBeVisible();
    expect(screen.getAllByRole('status').length).toBeGreaterThanOrEqual(6);
    expect(screen.getAllByText('Queued for research')).toHaveLength(4);
  });
});

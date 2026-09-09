/**
 * The research stream as a pure reducer.
 *
 * Every event the backend can send maps to one state transition here, with no
 * network, timers or React involved. That makes the interesting behaviour —
 * partial sections rendering, a section failing while the others continue,
 * a stream that ends without completing — testable directly, and keeps the
 * hook that owns the fetch small enough to read in one sitting.
 */
import {
  SECTION_ORDER,
  type FinancialHighlights,
  type NewsItem,
  type Person,
  type ReportSummary,
  type ResearchEvent,
  type ResearchReport,
  type RiskItem,
  type SectionKey,
  type Source,
} from '@/lib/types';

export type Phase =
  | 'idle'
  | 'planning'
  | 'searching'
  | 'writing'
  | 'complete'
  | 'error'
  | 'cancelled';

export type SectionStatus = 'pending' | 'streaming' | 'complete' | 'failed';

export interface SectionState {
  status: SectionStatus;
  /** Best-effort object repaired from a half-streamed response. */
  partial: Record<string, unknown> | null;
  data: string | Person[] | NewsItem[] | FinancialHighlights | RiskItem[] | null;
  sources: Source[];
  message: string | null;
}

export interface ActivityEntry {
  id: string;
  tool: string;
  query: string;
  status: 'running' | 'done' | 'failed';
  resultCount: number | null;
  newSources: number | null;
  elapsedMs: number | null;
  message: string | null;
}

export interface StreamState {
  phase: Phase;
  companyName: string;
  statusMessage: string | null;
  sections: Record<SectionKey, SectionState>;
  activity: ActivityEntry[];
  evidenceCount: number;
  report: ResearchReport | null;
  savedSummary: ReportSummary | null;
  error: { message: string; retryable: boolean } | null;
  warnings: string[];
}

export type StreamAction =
  | { type: 'reset' }
  | { type: 'start'; companyName: string }
  | { type: 'event'; event: ResearchEvent }
  | { type: 'cancelled' }
  | { type: 'transportError'; message: string; retryable?: boolean }
  | { type: 'streamEndedEarly' }
  | { type: 'loadReport'; report: ResearchReport };

const emptySection = (): SectionState => ({
  status: 'pending',
  partial: null,
  data: null,
  sources: [],
  message: null,
});

const emptySections = (): Record<SectionKey, SectionState> =>
  Object.fromEntries(SECTION_ORDER.map((key) => [key, emptySection()])) as Record<
    SectionKey,
    SectionState
  >;

export const initialStreamState: StreamState = {
  phase: 'idle',
  companyName: '',
  statusMessage: null,
  sections: emptySections(),
  activity: [],
  evidenceCount: 0,
  report: null,
  savedSummary: null,
  error: null,
  warnings: [],
};

const asString = (value: unknown, fallback = ''): string =>
  typeof value === 'string' ? value : fallback;

const asNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

function withSection(
  state: StreamState,
  key: SectionKey,
  patch: Partial<SectionState>,
): StreamState {
  const current = state.sections[key];
  if (!current) return state;
  return { ...state, sections: { ...state.sections, [key]: { ...current, ...patch } } };
}

function isSectionKey(value: unknown): value is SectionKey {
  return typeof value === 'string' && (SECTION_ORDER as readonly string[]).includes(value);
}

export function streamReducer(state: StreamState, action: StreamAction): StreamState {
  switch (action.type) {
    case 'reset':
      return initialStreamState;

    case 'start':
      return {
        ...initialStreamState,
        phase: 'planning',
        companyName: action.companyName,
        statusMessage: 'Starting research',
      };

    case 'cancelled':
      return state.phase === 'complete'
        ? state
        : { ...state, phase: 'cancelled', statusMessage: null };

    case 'transportError':
      return {
        ...state,
        phase: 'error',
        statusMessage: null,
        error: { message: action.message, retryable: action.retryable ?? true },
      };

    case 'streamEndedEarly':
      // The connection closed without `research_completed` or `research_failed`
      // — a dropped network or a killed server. Say so rather than spinning.
      if (state.phase === 'complete' || state.phase === 'error' || state.phase === 'cancelled') {
        return state;
      }
      return {
        ...state,
        phase: 'error',
        statusMessage: null,
        error: {
          message: 'The connection to the research service dropped before the briefing finished.',
          retryable: true,
        },
      };

    case 'loadReport':
      return loadReport(action.report);

    case 'event':
      return applyEvent(state, action.event);

    default:
      return state;
  }
}

function loadReport(report: ResearchReport): StreamState {
  const sections = emptySections();
  for (const key of SECTION_ORDER) {
    const value = report[key] as SectionState['data'];
    sections[key] = {
      status: value === null || value === undefined ? 'failed' : 'complete',
      partial: null,
      data: value ?? null,
      sources: report.section_sources[key] ?? [],
      message: value === null || value === undefined ? 'No data was found for this section.' : null,
    };
  }
  return {
    ...initialStreamState,
    phase: 'complete',
    companyName: report.company_name,
    sections,
    report,
    savedSummary: {
      id: report.id,
      company_name: report.company_name,
      created_at: report.created_at,
    },
    warnings: report.warnings ?? [],
  };
}

function applyEvent(state: StreamState, { event, data }: ResearchEvent): StreamState {
  switch (event) {
    case 'research_started':
      return { ...state, companyName: asString(data.company_name, state.companyName) };

    case 'stage': {
      const stage = asString(data.stage);
      const phase: Phase =
        stage === 'searching' ? 'searching' : stage === 'synthesizing' ? 'writing' : 'planning';
      return {
        ...state,
        phase,
        statusMessage: asString(data.message) || state.statusMessage,
        evidenceCount: asNumber(data.evidence_count) ?? state.evidenceCount,
      };
    }

    case 'tool_call': {
      const entry: ActivityEntry = {
        id: asString(data.id, `${state.activity.length}`),
        tool: asString(data.tool, 'web_search'),
        query: asString(data.query),
        status: 'running',
        resultCount: null,
        newSources: null,
        elapsedMs: null,
        message: null,
      };
      return { ...state, phase: 'searching', activity: [...state.activity, entry] };
    }

    case 'tool_result': {
      const id = asString(data.id);
      const error = asString(data.error) || null;
      return {
        ...state,
        activity: state.activity.map((entry) =>
          entry.id === id
            ? {
                ...entry,
                status: error ? 'failed' : 'done',
                resultCount: asNumber(data.result_count),
                newSources: asNumber(data.new_sources),
                elapsedMs: asNumber(data.elapsed_ms),
                message: error,
              }
            : entry,
        ),
      };
    }

    case 'section_started': {
      if (!isSectionKey(data.section)) return state;
      return withSection({ ...state, phase: 'writing' }, data.section, { status: 'streaming' });
    }

    case 'section_delta': {
      if (!isSectionKey(data.section)) return state;
      const partial =
        data.partial && typeof data.partial === 'object'
          ? (data.partial as Record<string, unknown>)
          : null;
      if (!partial) return state;
      return withSection(state, data.section, { status: 'streaming', partial });
    }

    case 'section_completed': {
      if (!isSectionKey(data.section)) return state;
      return withSection(state, data.section, {
        status: 'complete',
        data: (data.data ?? null) as SectionState['data'],
        sources: Array.isArray(data.sources) ? (data.sources as Source[]) : [],
        partial: null,
        message: null,
      });
    }

    case 'section_failed': {
      if (!isSectionKey(data.section)) return state;
      const message = asString(data.message, 'This section could not be completed.');
      return withSection(
        { ...state, warnings: [...state.warnings, message] },
        data.section,
        { status: 'failed', message, partial: null },
      );
    }

    case 'research_completed': {
      const report = data.report as ResearchReport | undefined;
      if (!report) return { ...state, phase: 'complete', statusMessage: null };
      // Reconcile against the persisted report so what is on screen is exactly
      // what was saved, then keep the live sources we already streamed.
      const loaded = loadReport(report);
      return {
        ...loaded,
        activity: state.activity,
        evidenceCount: state.evidenceCount,
        sections: Object.fromEntries(
          SECTION_ORDER.map((key) => {
            const fromReport = loaded.sections[key]!;
            const live = state.sections[key]!;
            return [
              key,
              {
                ...fromReport,
                sources: fromReport.sources.length ? fromReport.sources : live.sources,
                message: fromReport.status === 'failed' ? (live.message ?? fromReport.message) : null,
              },
            ];
          }),
        ) as Record<SectionKey, SectionState>,
      };
    }

    case 'research_failed':
      return {
        ...state,
        phase: 'error',
        statusMessage: null,
        error: {
          message: asString(data.message, 'Research could not be completed. Please try again.'),
          retryable: data.retryable !== false,
        },
      };

    default:
      // Unknown event names are ignored so the backend can add events without
      // breaking a frontend that has not shipped yet.
      return state;
  }
}

export const isStreaming = (phase: Phase): boolean =>
  phase === 'planning' || phase === 'searching' || phase === 'writing';

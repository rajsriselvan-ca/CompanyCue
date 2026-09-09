export const SECTION_ORDER = ['overview', 'key_people', 'news', 'financials', 'risks'] as const;

export type SectionKey = (typeof SECTION_ORDER)[number];

export const SECTION_LABELS: Record<SectionKey, string> = {
  overview: 'Company overview',
  key_people: 'Key people',
  news: 'Recent news',
  financials: 'Financial highlights',
  risks: 'Risk factors',
};

export interface Source {
  title: string;
  url: string;
  published?: string | null;
}

export interface Person {
  name: string;
  title: string;
}

export interface NewsItem {
  headline: string;
  summary: string;
  date?: string | null;
  citation?: number | null;
}

export interface FinancialHighlights {
  revenue: string | null;
  employee_count: string | null;
  market_cap: string | null;
  yoy_growth: string | null;
}

export interface RiskItem {
  title: string;
  details: string;
  citation?: number | null;
}

export interface ReportSummary {
  id: string;
  company_name: string;
  created_at: string;
}

export interface ResearchReport extends ReportSummary {
  overview: string | null;
  key_people: Person[] | null;
  news: NewsItem[] | null;
  financials: FinancialHighlights | null;
  risks: RiskItem[] | null;
  section_sources: Partial<Record<SectionKey, Source[]>>;
  warnings: string[];
}

/** A parsed SSE frame, before it is interpreted as a research event. */
export interface SSEFrame {
  id?: string;
  event: string;
  data: string;
  retry?: number;
}

export type ResearchEventName =
  | 'research_started'
  | 'stage'
  | 'tool_call'
  | 'tool_result'
  | 'section_started'
  | 'section_delta'
  | 'section_completed'
  | 'section_failed'
  | 'research_completed'
  | 'research_failed';

export interface ResearchEvent {
  id?: string;
  event: ResearchEventName | string;
  data: Record<string, unknown>;
}

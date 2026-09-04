export const sectionOrder = [
  'overview',
  'key_people',
  'news',
  'financials',
  'risks',
] as const;

export type SectionKey = (typeof sectionOrder)[number];

export interface Source {
  title: string;
  url: string;
}

export interface Person {
  name: string;
  title: string;
}

export interface NewsItem {
  headline: string;
  summary: string;
  date: string | null;
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

export interface StreamEvent<T = Record<string, unknown>> {
  id?: string;
  event: string;
  data: T;
}

export function createDraftReport(companyName: string): ResearchReport {
  return {
    id: 'draft',
    company_name: companyName,
    created_at: new Date().toISOString(),
    overview: null,
    key_people: null,
    news: null,
    financials: null,
    risks: null,
    section_sources: {},
    warnings: [],
  };
}

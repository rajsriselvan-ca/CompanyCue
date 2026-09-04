import { FileSearch, History, Trash2 } from 'lucide-react';

import { Skeleton } from '@/components/ui/skeleton';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from '@/components/ui/sidebar';
import type { ReportSummary } from '@/lib/briefd-types';
import { formatRelativeTime } from '@/lib/time';

interface HistorySidebarProps {
  reports: ReportSummary[];
  selectedId: string | null;
  loading: boolean;
  error: string | null;
  onSelect: (report: ReportSummary) => void;
  onDelete: (report: ReportSummary) => void;
}

export function HistorySidebar({
  reports,
  selectedId,
  loading,
  error,
  onSelect,
  onDelete,
}: HistorySidebarProps) {
  const { setOpenMobile } = useSidebar();

  const select = (report: ReportSummary) => {
    onSelect(report);
    setOpenMobile(false);
  };

  return (
    <Sidebar className="briefd-sidebar border-r-0" collapsible="offcanvas">
      <SidebarHeader className="border-b border-white/10 px-5 py-5">
        <div className="flex items-center gap-3">
          <div className="grid size-9 place-items-center rounded-xl bg-[var(--signal)] text-white shadow-[0_8px_28px_rgba(255,94,58,.28)]">
            <FileSearch className="size-5" />
          </div>
          <div>
            <div className="text-lg font-semibold tracking-[-0.03em] text-white">Briefd</div>
            <div className="text-xs text-white/50">Company intelligence</div>
          </div>
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup className="px-3 py-4">
          <SidebarGroupLabel className="gap-2 px-2 text-[0.72rem] font-semibold uppercase tracking-[0.14em] text-white/40">
            <History className="size-3.5" /> Recent briefings
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu className="mt-2 gap-1">
              {loading
                ? [0, 1, 2].map((item) => (
                    <SidebarMenuItem className="px-2 py-1" key={item}>
                      <Skeleton className="h-12 bg-white/8" />
                    </SidebarMenuItem>
                  ))
                : null}

              {!loading && reports.length === 0 ? (
                <SidebarMenuItem>
                  <div className="mx-2 mt-2 rounded-xl border border-dashed border-white/15 px-4 py-5 text-sm leading-6 text-white/48">
                    {error ?? 'Your researched companies will appear here.'}
                  </div>
                </SidebarMenuItem>
              ) : null}

              {reports.map((report) => (
                <SidebarMenuItem key={report.id}>
                  <SidebarMenuButton
                    className="h-auto min-h-14 items-start rounded-xl px-3 py-2.5 pr-10 text-white/72 hover:bg-white/8 hover:text-white data-active:bg-white/10 data-active:text-white"
                    isActive={selectedId === report.id}
                    onClick={() => select(report)}
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium">{report.company_name}</span>
                      <span className="mt-0.5 block text-xs font-normal text-white/38">
                        {formatRelativeTime(report.created_at)}
                      </span>
                    </span>
                  </SidebarMenuButton>
                  <SidebarMenuAction
                    aria-label={`Delete ${report.company_name} report`}
                    className="right-2 !top-1/2 size-7 -translate-y-1/2 text-white/35 hover:bg-white/10 hover:text-white"
                    onClick={() => onDelete(report)}
                    showOnHover
                  >
                    <Trash2 />
                  </SidebarMenuAction>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="border-t border-white/10 px-5 py-4 text-xs leading-5 text-white/40">
        Company intelligence powered by Gemini Flash.
      </SidebarFooter>
    </Sidebar>
  );
}

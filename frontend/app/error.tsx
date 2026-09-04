'use client';

import { useEffect } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/button';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--canvas)] px-4">
      <div className="flex w-full max-w-md flex-col items-center gap-4 rounded-2xl border border-red-200 bg-red-50 px-6 py-8 text-center shadow-[0_24px_70px_rgba(17,34,68,.06)]">
        <span className="grid size-11 place-items-center rounded-full bg-red-100 text-red-600">
          <AlertTriangle className="size-5" />
        </span>
        <div>
          <h1 className="text-lg font-semibold text-[var(--ink)]">Something went wrong</h1>
          <p className="mt-1.5 text-sm leading-6 text-[var(--muted-ink)]">
            Briefd hit an unexpected error. Your saved reports are safe — try again, and
            if it keeps happening, reload the page.
          </p>
        </div>
        <Button
          className="border-red-200 bg-white text-red-800 hover:bg-red-100"
          onClick={reset}
          variant="outline"
        >
          <RefreshCw data-icon="inline-start" /> Try again
        </Button>
      </div>
    </div>
  );
}

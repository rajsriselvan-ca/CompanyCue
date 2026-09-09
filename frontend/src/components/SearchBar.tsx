import { useEffect, useRef, useState, type FormEvent } from 'react';

import { Button, Spinner } from '@/components/ui/primitives';

/**
 * Mirrors the server's validation so obvious mistakes are caught before a
 * request is made. The server still validates — this is for speed, not trust.
 */
export function validateCompanyName(value: string): string | null {
  const name = value.trim();
  if (name.length < 2) return 'Enter a company name with at least two characters.';
  if (name.length > 120) return 'Keep the company name under 120 characters.';
  if (/^https?:\/\//i.test(name) || name.includes('@')) {
    return 'Enter a company name, not a URL or email address.';
  }
  if ((name.match(/[A-Za-z0-9]/g) ?? []).length < 2) {
    return 'Enter a recognizable company name.';
  }
  if (/^(.)\1{3,}$/i.test(name)) return 'Enter a recognizable company name.';
  return null;
}

interface SearchBarProps {
  streaming: boolean;
  onSubmit: (companyName: string) => void;
  onCancel: () => void;
}

export function SearchBar({ streaming, onSubmit, onCancel }: SearchBarProps) {
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const focusSearch = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
    };
    window.addEventListener('keydown', focusSearch);
    return () => window.removeEventListener('keydown', focusSearch);
  }, []);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const message = validateCompanyName(value);
    if (message) {
      setError(message);
      inputRef.current?.focus();
      return;
    }
    setError(null);
    onSubmit(value);
  };

  return (
    <form className="flex flex-1 items-start gap-2" noValidate onSubmit={submit}>
      <div className="min-w-0 flex-1">
        <label className="sr-only" htmlFor="company-name">
          Company name
        </label>
        <div className="relative">
          <span
            aria-hidden="true"
            className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted"
          >
            <SearchIcon />
          </span>
          <input
            aria-describedby={error ? 'company-name-error' : undefined}
            aria-invalid={error ? true : undefined}
            autoComplete="organization"
            className="h-11 w-full rounded-xl border border-line-strong bg-surface pl-10 pr-16 text-[0.95rem] text-ink shadow-raised outline-none placeholder:text-muted/80 focus-visible:border-brand focus-visible:ring-3 focus-visible:ring-brand-soft"
            id="company-name"
            onChange={(event) => {
              setValue(event.target.value);
              if (error) setError(null);
            }}
            placeholder="Research a company — try Stripe, Datadog, Klarna"
            ref={inputRef}
            spellCheck={false}
            value={value}
          />
          <kbd className="pointer-events-none absolute right-3 top-1/2 hidden -translate-y-1/2 rounded-md border border-line bg-raised px-1.5 py-0.5 font-mono text-[0.68rem] font-semibold text-muted sm:block">
            ⌘K
          </kbd>
        </div>
        {error ? (
          <p className="mt-1.5 text-sm text-danger" id="company-name-error" role="alert">
            {error}
          </p>
        ) : null}
      </div>

      {streaming ? (
        <Button className="h-11 shrink-0" onClick={onCancel} type="button" variant="secondary">
          Stop
        </Button>
      ) : null}

      <Button className="h-11 shrink-0" disabled={streaming} type="submit">
        {streaming ? <Spinner /> : null}
        <span className="hidden sm:inline">{streaming ? 'Researching…' : 'Build briefing'}</span>
        <span className="sm:hidden">{streaming ? '…' : 'Go'}</span>
      </Button>
    </form>
  );
}

function SearchIcon() {
  return (
    <svg fill="none" height="18" viewBox="0 0 24 24" width="18">
      <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
      <path d="m16.5 16.5 4 4" stroke="currentColor" strokeLinecap="round" strokeWidth="2" />
    </svg>
  );
}

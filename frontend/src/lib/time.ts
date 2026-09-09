const relative = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });

const RANGES: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ['year', 1000 * 60 * 60 * 24 * 365],
  ['month', 1000 * 60 * 60 * 24 * 30],
  ['day', 1000 * 60 * 60 * 24],
  ['hour', 1000 * 60 * 60],
  ['minute', 1000 * 60],
];

/** "3 minutes ago". Falls back to the raw value if the date is unparseable. */
export function formatRelativeTime(value: string, now: number = Date.now()): string {
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return value;

  const difference = timestamp - now;
  const magnitude = Math.abs(difference);
  for (const [unit, milliseconds] of RANGES) {
    if (magnitude >= milliseconds) {
      return relative.format(Math.round(difference / milliseconds), unit);
    }
  }
  return 'just now';
}

export function formatAbsoluteTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

/** News dates arrive as YYYY-MM-DD; render them without a timezone shift. */
export function formatNewsDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return value;
  const [, year, month, day] = match;
  const date = new Date(Number(year), Number(month) - 1, Number(day));
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('en', { dateStyle: 'medium' }).format(date);
}

export function hostnameOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

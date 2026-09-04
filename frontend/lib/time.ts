const relativeFormatter = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });

export function formatRelativeTime(value: string, now = Date.now()): string {
  const difference = new Date(value).getTime() - now;
  const absolute = Math.abs(difference);
  const ranges: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ['year', 1000 * 60 * 60 * 24 * 365],
    ['month', 1000 * 60 * 60 * 24 * 30],
    ['day', 1000 * 60 * 60 * 24],
    ['hour', 1000 * 60 * 60],
    ['minute', 1000 * 60],
  ];

  for (const [unit, milliseconds] of ranges) {
    if (absolute >= milliseconds) return relativeFormatter.format(Math.round(difference / milliseconds), unit);
  }
  return 'just now';
}

export function formatReportDate(value: string): string {
  return new Intl.DateTimeFormat('en', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

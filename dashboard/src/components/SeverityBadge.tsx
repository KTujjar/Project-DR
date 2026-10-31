import type { Severity } from '../logic/severity'

// Hex colors for the map, Tailwind classes for everything else.
export const SEVERITY_COLOR: Record<Severity, string> = {
  ok: '#16a34a',
  low: '#eab308',
  critical: '#dc2626',
}

const BADGE_CLASS: Record<Severity, string> = {
  ok: 'bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200',
  low: 'bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200',
  critical: 'bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200',
}

const LABEL: Record<Severity, string> = { ok: 'OK', low: 'Low', critical: 'Critical' }

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${BADGE_CLASS[severity]}`}>{LABEL[severity]}</span>
  )
}

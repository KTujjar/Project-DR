import type { CrowdStats } from '../types/crowdStats'

// Formatting for the per-camera crowd metrics view. Pure, so the panel only renders.

export const STATS_STALE_AFTER_S = 10 // reliefvision emits every 2 s; 10 s means it stopped

export function peopleLabel(stats: Pick<CrowdStats, 'people' | 'people_is_lower_bound'>): string {
  return stats.people_is_lower_bound ? `≥ ${stats.people}` : String(stats.people)
}

export function percent(fraction: number | null): string {
  return fraction === null ? '–' : `${Math.round(fraction * 100)}%`
}

export function aidsSummary(aids: CrowdStats['mobility_aids']): string {
  if (aids === null) return 'detector off'
  const seen = Object.entries(aids).filter(([, n]) => (n ?? 0) > 0)
  if (seen.length === 0) return 'none visible'
  return seen.map(([kind, n]) => `${n} ${kind}${n === 1 || kind === 'crutches' ? '' : 's'}`).join(', ')
}

export function flowLabel(stats: Pick<CrowdStats, 'dominant_flow' | 'flow_coherence' | 'counterflow'>): string {
  if (stats.dominant_flow === null) return '–'
  const coherence = stats.flow_coherence === null ? '' : ` (${percent(stats.flow_coherence)} aligned)`
  return `${stats.dominant_flow}${coherence}${stats.counterflow ? ', counterflow' : ''}`
}

export function speedLabel(bodyHeightsPerS: number | null): string {
  return bodyHeightsPerS === null ? '–' : `${bodyHeightsPerS.toFixed(2)} body-heights/s`
}

export function isStatsStale(ts: number, now = Date.now()): boolean {
  return now / 1000 - ts > STATS_STALE_AFTER_S
}

// Crowd grid cell (0..1.5, 1 = at capacity) to a background color: transparent -> amber -> red.
export function gridCellColor(value: number): string {
  const v = Math.max(0, Math.min(value, 1.5)) / 1.5
  if (v === 0) return 'rgba(148, 163, 184, 0.08)'
  const hue = 45 - 45 * v // amber (45) to red (0)
  return `hsla(${Math.round(hue)}, 90%, 50%, ${(0.25 + 0.65 * v).toFixed(2)})`
}

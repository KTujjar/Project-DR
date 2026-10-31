import type { PeopleCount } from '../types/schemas'

export type Trend = 'up' | 'down' | 'flat'

// Latest count per camera, then combined per site (sum of cameras, or max if they overlap).
export function siteHeadcounts(counts: PeopleCount[], mode: 'sum' | 'max' = 'sum'): Record<string, number> {
  const latest = new Map<string, PeopleCount>()
  for (const c of counts) {
    const prev = latest.get(c.camera_id)
    if (!prev || c.timestamp > prev.timestamp) latest.set(c.camera_id, c)
  }

  const bySite: Record<string, number> = {}
  for (const c of latest.values()) {
    const current = bySite[c.site_id] ?? 0
    bySite[c.site_id] = mode === 'sum' ? current + c.people_count : Math.max(current, c.people_count)
  }
  return bySite
}

export function trend(previous: number | undefined, current: number): Trend {
  if (previous === undefined || previous === current) return 'flat'
  return current > previous ? 'up' : 'down'
}

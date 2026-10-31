import type { DashboardSnapshot } from '../types/schemas'
import { config as defaultConfig, type Config } from './config'

export type SourceName = 'people counts' | 'cameras' | 'inventory'

// Continuous feeds only. Texts and dispatches are event-driven, so a quiet period is not a fault.
const NEWEST: Record<SourceName, (s: DashboardSnapshot) => string[]> = {
  'people counts': (s) => s.peopleCounts.map((p) => p.timestamp),
  cameras: (s) => s.cameras.map((c) => c.last_frame_at),
  inventory: (s) => s.inventory.map((r) => r.timestamp),
}

export interface StaleSource {
  source: SourceName
  ageSeconds: number
}

// Sources whose newest record is older than the stale threshold.
export function staleSources(snapshot: DashboardSnapshot, now: number, cfg: Config = defaultConfig): StaleSource[] {
  const result: StaleSource[] = []
  for (const [source, timestamps] of Object.entries(NEWEST) as [SourceName, (s: DashboardSnapshot) => string[]][]) {
    const times = timestamps(snapshot).map((t) => Date.parse(t)).filter((t) => !Number.isNaN(t))
    if (times.length === 0) continue
    const ageSeconds = Math.round((now - Math.max(...times)) / 1000)
    if (ageSeconds > cfg.staleAfterSeconds) result.push({ source, ageSeconds })
  }
  return result
}


import { ITEM_TYPES, type ItemType } from '../types/schemas'
import { config as defaultConfig, type Config } from './config'
import type { ItemStatus } from './need'

export type Severity = 'ok' | 'low' | 'critical'

export const SEVERITY_RANK: Record<Severity, number> = { ok: 0, low: 1, critical: 2 }

export function severityFromCoverage(coverage: number, cfg: Config = defaultConfig): Severity {
  if (coverage >= cfg.severity.ok) return 'ok'
  if (coverage >= cfg.severity.low) return 'low'
  return 'critical'
}

export interface SiteSeverity {
  severity: Severity
  worstItem: ItemType | null // null when nothing is short
  overCapacity: boolean
}

// Severity from the worst item's coverage; Critical regardless when headcount exceeds 90% of capacity.
export function siteSeverity(
  items: Record<ItemType, ItemStatus>,
  headcount: number,
  capacity?: number,
  cfg: Config = defaultConfig,
): SiteSeverity {
  let worstItem: ItemType | null = null
  let worstCoverage = Infinity
  for (const item of ITEM_TYPES) {
    if (items[item].coverage < worstCoverage) {
      worstCoverage = items[item].coverage
      worstItem = item
    }
  }

  const overCapacity = capacity !== undefined && capacity > 0 && headcount > capacity * cfg.capacityCriticalRatio
  const fromItems = severityFromCoverage(worstCoverage, cfg)
  return {
    severity: overCapacity ? 'critical' : fromItems,
    worstItem: fromItems === 'ok' ? null : worstItem,
    overCapacity,
  }
}


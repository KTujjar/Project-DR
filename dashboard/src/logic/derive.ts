import type { DashboardSnapshot, Dispatch } from '../types/schemas'
import { config as defaultConfig, type Config } from './config'
import { siteHeadcounts } from './headcount'
import { latestStock, type ItemQuantities } from './need'
import { priorityList, type Issue } from './priority'
import { buildSiteRows, type SiteRow } from './sites'
import { suggestDispatches } from './suggestions'

export interface Derived {
  headcounts: Record<string, number>
  stock: Record<string, ItemQuantities>
  rows: SiteRow[]
  priorities: Issue[]
  suggestions: Dispatch[]
}

// Everything the panels need, computed from one snapshot.
export function deriveAll(
  snapshot: DashboardSnapshot,
  previousHeadcounts: Record<string, number> = {},
  now: string = new Date().toISOString(),
  cfg: Config = defaultConfig,
): Derived {
  const headcounts = siteHeadcounts(snapshot.peopleCounts, cfg.headcountMode)
  const stock = latestStock(snapshot.inventory)
  const rows = buildSiteRows(snapshot.locations, headcounts, previousHeadcounts, stock, snapshot.cameras, cfg)
  return {
    headcounts,
    stock,
    rows,
    priorities: priorityList(rows, snapshot.messages, snapshot.cameras, snapshot.locations, cfg),
    suggestions: suggestDispatches(rows, snapshot.locations, stock, snapshot.dispatches, now, cfg),
  }
}

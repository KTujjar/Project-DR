import type { CameraFeed, ItemType, Location } from '../types/schemas'
import { config as defaultConfig, type Config } from './config'
import { trend, type Trend } from './headcount'
import { computeNeed, emptyQuantities, itemStatuses, type ItemQuantities, type ItemStatus } from './need'
import { siteSeverity, type Severity } from './severity'

export interface SiteRow {
  location: Location
  headcount: number
  trend: Trend
  capacityRatio: number | null
  items: Record<ItemType, ItemStatus>
  severity: Severity
  worstItem: ItemType | null
  overCapacity: boolean
  offlineCameras: number
}

// One row per shelter combining headcount, stock and severity.
export function buildSiteRows(
  locations: Location[],
  headcounts: Record<string, number>,
  previousHeadcounts: Record<string, number>,
  stock: Record<string, ItemQuantities>,
  cameras: CameraFeed[],
  cfg: Config = defaultConfig,
): SiteRow[] {
  return locations
    .filter((l) => l.kind === 'shelter')
    .map((location) => {
      const headcount = headcounts[location.id] ?? 0
      const items = itemStatuses(computeNeed(headcount, location.capacity, cfg), stock[location.id] ?? emptyQuantities())
      const sev = siteSeverity(items, headcount, location.capacity, cfg)
      return {
        location,
        headcount,
        trend: trend(previousHeadcounts[location.id], headcount),
        capacityRatio: location.capacity ? headcount / location.capacity : null,
        items,
        ...sev,
        offlineCameras: cameras.filter((c) => c.site_id === location.id && !c.online).length,
      }
    })
}

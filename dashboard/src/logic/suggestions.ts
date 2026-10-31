import { ITEM_TYPES, type Dispatch, type ItemType, type Location } from '../types/schemas'
import { config as defaultConfig, type Config } from './config'
import { haversineKm } from './geo'
import { emptyQuantities, type ItemQuantities } from './need'
import type { SiteRow } from './sites'

const ACTIVE: Dispatch['status'][] = ['pending', 'en_route']

function sumItems(dispatches: Dispatch[], key: 'to_site' | 'from_site', statuses: Dispatch['status'][]) {
  const totals: Record<string, ItemQuantities> = {}
  for (const d of dispatches) {
    if (!statuses.includes(d.status)) continue
    const site = d[key]
    totals[site] ??= emptyQuantities()
    for (const [item, qty] of Object.entries(d.items) as [ItemType, number][]) totals[site][item] += qty
  }
  return totals
}

export function etaMinutes(km: number, cfg: Config = defaultConfig): number {
  return Math.max(1, Math.ceil((km / cfg.truckSpeedKmh) * 60))
}

// Greedy dispatch suggestions: worst-covered shortfalls first, filled from the nearest
// depot with surplus above its safety reserve, split across depots when needed.
// Shortfalls already covered by pending / en-route dispatches are skipped. Each suggestion
// adds a buffer (config.suggestionBufferRatio of the need) on top of the shortfall.
export function suggestDispatches(
  rows: SiteRow[],
  locations: Location[],
  stock: Record<string, ItemQuantities>,
  dispatches: Dispatch[],
  now: string,
  cfg: Config = defaultConfig,
): Dispatch[] {
  const depots = locations.filter((l) => l.kind === 'depot')
  const incoming = sumItems(dispatches, 'to_site', ACTIVE)
  // Pending dispatches have not left yet, so their stock is still counted at the depot.
  const committed = sumItems(dispatches, 'from_site', ['pending'])

  const available: Record<string, ItemQuantities> = {}
  for (const depot of depots) {
    const onHand = stock[depot.id] ?? emptyQuantities()
    available[depot.id] = emptyQuantities()
    for (const item of ITEM_TYPES) {
      const spare = Math.floor(onHand[item] * (1 - cfg.depotReserveRatio)) - (committed[depot.id]?.[item] ?? 0)
      available[depot.id][item] = Math.max(0, spare)
    }
  }

  const shortfalls = rows
    .flatMap((row) =>
      ITEM_TYPES.map((item) => {
        const { need, shortfall, coverage } = row.items[item]
        const uncovered = shortfall - (incoming[row.location.id]?.[item] ?? 0)
        return {
          row,
          item,
          coverage,
          uncovered,
          minimum: need * cfg.minSuggestionRatio,
          amount: uncovered + Math.ceil(need * cfg.suggestionBufferRatio),
        }
      }),
    )
    .filter((s) => s.uncovered > 0 && s.uncovered >= s.minimum)
    .sort((a, b) => a.coverage - b.coverage)

  const byRoute = new Map<string, Dispatch>()
  for (const s of shortfalls) {
    const target = s.row.location
    const nearest = [...depots].sort((a, b) => haversineKm(a, target) - haversineKm(b, target))
    let remaining = s.amount
    for (const depot of nearest) {
      if (remaining <= 0) break
      const take = Math.min(remaining, available[depot.id][s.item])
      if (take <= 0) continue
      available[depot.id][s.item] -= take
      remaining -= take

      const id = `sugg_${target.id}_${depot.id}`
      const dispatch = byRoute.get(id) ?? {
        dispatch_id: id,
        from_site: depot.id,
        to_site: target.id,
        items: {},
        status: 'suggested' as const,
        eta_minutes: etaMinutes(haversineKm(depot, target), cfg),
        created_at: now,
        updated_at: now,
      }
      dispatch.items[s.item] = (dispatch.items[s.item] ?? 0) + take
      byRoute.set(id, dispatch)
    }
  }
  return [...byRoute.values()]
}


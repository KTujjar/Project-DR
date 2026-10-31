import type { CameraFeed, Location, TextMessage } from '../types/schemas'
import { config as defaultConfig, type Config } from './config'
import type { Severity } from './severity'
import type { SiteRow } from './sites'

export type IssueKind = 'shortfall' | 'capacity' | 'needs_review' | 'camera_offline'

export interface Issue {
  id: string
  kind: IssueKind
  site_id?: string
  severity: Severity
  title: string
  score: number
}

const URGENCY_FACTOR: Record<string, number> = { critical: 1, high: 0.75, medium: 0.5, low: 0.4 }
const UNPARSED_FACTOR = 0.4

const ITEM_LABEL: Record<string, string> = {
  water_L: 'water',
  food_meals: 'food',
  medical_kits: 'medical kits',
  blankets: 'blankets',
  cots: 'cots',
}

// Ranked list of issues: severity weight x people affected, plus bonuses for
// texts needing review and offline cameras at occupied sites. Highest first.
export function priorityList(
  rows: SiteRow[],
  messages: TextMessage[],
  cameras: CameraFeed[],
  locations: Location[],
  cfg: Config = defaultConfig,
): Issue[] {
  const p = cfg.priority
  const issues: Issue[] = []
  const nameOf = (id?: string) => locations.find((l) => l.id === id)?.name ?? id ?? 'Unknown site'

  for (const row of rows) {
    const id = row.location.id
    if (row.worstItem) {
      const sev = row.items[row.worstItem].coverage < cfg.severity.low ? 'critical' : 'low'
      const pct = Math.round(row.items[row.worstItem].coverage * 100)
      issues.push({
        id: `shortfall_${id}`,
        kind: 'shortfall',
        site_id: id,
        severity: sev,
        title: `${row.location.name}: ${ITEM_LABEL[row.worstItem]} at ${pct}% of need`,
        score: (sev === 'critical' ? p.criticalWeight : p.lowWeight) * row.headcount,
      })
    }
    if (row.overCapacity && row.capacityRatio !== null) {
      issues.push({
        id: `capacity_${id}`,
        kind: 'capacity',
        site_id: id,
        severity: 'critical',
        title: `${row.location.name}: at ${Math.round(row.capacityRatio * 100)}% capacity`,
        score: p.criticalWeight * row.headcount,
      })
    }
  }

  for (const m of messages) {
    if (m.direction !== 'in' || !m.needs_review) continue
    const factor = m.parsed ? (URGENCY_FACTOR[m.parsed.urgency] ?? UNPARSED_FACTOR) : UNPARSED_FACTOR
    const preview = m.body.length > 48 ? `${m.body.slice(0, 45)}...` : m.body
    issues.push({
      id: `review_${m.message_id}`,
      kind: 'needs_review',
      site_id: m.parsed?.site_id,
      severity: m.parsed?.urgency === 'critical' ? 'critical' : 'low',
      title: `Text needs review: "${preview}"`,
      score: p.needsReviewBonus * factor,
    })
  }

  const headcountBySite = new Map(rows.map((r) => [r.location.id, r.headcount]))
  for (const cam of cameras) {
    if (cam.online || !(headcountBySite.get(cam.site_id) ?? 0)) continue
    issues.push({
      id: `camera_${cam.camera_id}`,
      kind: 'camera_offline',
      site_id: cam.site_id,
      severity: 'low',
      title: `Camera ${cam.camera_id} offline at ${nameOf(cam.site_id)}`,
      score: p.offlineCameraBonus,
    })
  }

  return issues.sort((a, b) => b.score - a.score)
}


import { describe, expect, it } from 'vitest'
import { createScenario } from '../data/mock/scenario'
import type { Dispatch } from '../types/schemas'
import { deriveAll } from './derive'

// Acceptance checks against the seeded Hanover flood scenario.
const NOW = '2026-01-01T00:00:00Z'

describe('scenario: derived values', () => {
  const snap = createScenario(Date.parse(NOW))
  const d = deriveAll(snap, {}, NOW)
  const row = (id: string) => d.rows.find((r) => r.location.id === id)!

  it('flags Shelter 3 Critical with the correct water shortfall', () => {
    const s3 = row('shelter_3')
    expect(s3.severity).toBe('critical')
    expect(s3.worstItem).toBe('water_L')
    expect(s3.items.water_L.shortfall).toBe(s3.headcount * 3 - 120)
  })

  it('flags Shelter 1 Low on medical kits', () => {
    expect(row('shelter_1')).toMatchObject({ severity: 'low', worstItem: 'medical_kits' })
  })

  it('suggests water for Shelter 3 from the nearest depot with surplus', () => {
    const s = d.suggestions.find((x) => x.to_site === 'shelter_3')!
    expect(s.from_site).toBe('depot_b')
    expect(s.status).toBe('suggested')
    const { shortfall, need } = row('shelter_3').items.water_L
    expect(s.items.water_L).toBe(shortfall + Math.ceil(need * 0.2))
    expect(s.eta_minutes).toBeGreaterThan(0)
  })

  it('ranks Shelter 3, the injury text and the offline camera as the top 3 issues', () => {
    const top = d.priorities.slice(0, 3)
    expect(top[0]).toMatchObject({ kind: 'shortfall', site_id: 'shelter_3' })
    expect(top.map((i) => i.kind)).toEqual(['shortfall', 'needs_review', 'camera_offline'])
    expect(top[1].title).toMatch(/cut his leg/)
  })
})

describe('suggestions vs active dispatches', () => {
  const snap = createScenario(Date.parse(NOW))
  const s3 = deriveAll(snap, {}, NOW).suggestions.find((x) => x.to_site === 'shelter_3')!

  it('does not re-suggest a shortfall covered by a pending dispatch', () => {
    const pending: Dispatch = { ...s3, dispatch_id: 'dsp_x', status: 'pending' }
    const again = deriveAll({ ...snap, dispatches: [...snap.dispatches, pending] }, {}, NOW)
    expect(again.suggestions.find((x) => x.to_site === 'shelter_3')).toBeUndefined()
  })

  it('splits across depots when the nearest cannot cover it', () => {
    const lowDepot = snap.inventory.map((r) =>
      r.site_id === 'depot_b' && r.item === 'water_L' ? { ...r, quantity: 100 } : r,
    )
    const split = deriveAll({ ...snap, inventory: lowDepot }, {}, NOW).suggestions.filter((x) => x.to_site === 'shelter_3')
    expect(split.map((x) => x.from_site).sort()).toEqual(['depot_a', 'depot_b'])
    expect(split.find((x) => x.from_site === 'depot_b')!.items.water_L).toBe(80) // 20% reserve kept
    const total = split.reduce((sum, x) => sum + (x.items.water_L ?? 0), 0)
    expect(total).toBe(s3.items.water_L)
  })

  it('ignores negligible shortfalls', () => {
    // Shelter 3 drinks a few litres below need: not worth a truck.
    const nearlyFull = snap.inventory.map((r) =>
      r.site_id === 'shelter_3' && r.item === 'water_L' ? { ...r, quantity: 505 } : r,
    )
    const s = deriveAll({ ...snap, inventory: nearlyFull }, {}, NOW).suggestions
    expect(s.find((x) => x.to_site === 'shelter_3')).toBeUndefined()
  })
})

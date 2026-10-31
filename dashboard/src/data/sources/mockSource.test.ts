import { describe, expect, it } from 'vitest'
import { createMockSource } from './mockSource'

const qty = (snap: Awaited<ReturnType<ReturnType<typeof createMockSource>['getSnapshot']>>, site: string, item: string) =>
  snap.inventory.find((r) => r.site_id === site && r.item === item)?.quantity

describe('mock scenario', () => {
  it('matches the seeded scenario shape', async () => {
    const snap = await createMockSource({ drift: false }).getSnapshot()
    expect(snap.locations.filter((l) => l.kind === 'shelter')).toHaveLength(4)
    expect(snap.locations.filter((l) => l.kind === 'depot')).toHaveLength(2)
    expect(snap.locations.filter((l) => l.kind === 'incident')).toHaveLength(1)
    // No simulated cameras (only real CV cameras get tiles); every shelter has a simulated headcount.
    expect(snap.cameras).toHaveLength(0)
    expect(snap.peopleCounts.map((c) => c.site_id).sort()).toEqual(['shelter_1', 'shelter_2', 'shelter_3', 'shelter_4'])
    expect(snap.messages).toHaveLength(15)
    expect(snap.messages.some((m) => m.needs_review && m.parsed?.urgency === 'critical')).toBe(true)
    expect(snap.messages.some((m) => m.needs_review && !m.parsed)).toBe(true)
    expect(snap.dispatches.map((d) => d.status).sort()).toEqual(['delivered', 'en_route', 'pending'])
  })

  it('returns copies so callers cannot mutate source state', async () => {
    const src = createMockSource({ drift: false })
    const a = await src.getSnapshot()
    a.locations.length = 0
    const b = await src.getSnapshot()
    expect(b.locations.length).toBe(7)
  })
})

describe('mock dispatch lifecycle', () => {
  it('moves a created dispatch pending -> en_route -> delivered and lands the stock', async () => {
    const src = createMockSource({ drift: false })
    const before = await src.getSnapshot()
    const waterBefore = qty(before, 'shelter_3', 'water_L')!
    const depotBefore = qty(before, 'depot_b', 'water_L')!

    await src.createDispatch({
      dispatch_id: 'sugg_test', from_site: 'depot_b', to_site: 'shelter_3', items: { water_L: 400 },
      status: 'suggested', eta_minutes: 2, created_at: '', updated_at: '',
    })

    const statuses: string[] = []
    let snap = before
    for (let i = 0; i < 6; i++) {
      snap = await src.getSnapshot()
      statuses.push(snap.dispatches.find((d) => d.dispatch_id === 'sugg_test')!.status)
    }
    expect(statuses[0]).toBe('pending')
    expect(statuses).toContain('en_route')
    expect(statuses.at(-1)).toBe('delivered')
    expect(qty(snap, 'shelter_3', 'water_L')).toBe(waterBefore + 400)
    expect(qty(snap, 'depot_b', 'water_L')).toBe(depotBefore - 400)
    expect(snap.messages.at(-1)!.direction).toBe('out')
  })

  it('cancels pending dispatches but not delivered ones', async () => {
    const src = createMockSource({ drift: false })
    await src.cancelDispatch('dsp_003')
    await src.cancelDispatch('dsp_001')
    const snap = await src.getSnapshot()
    expect(snap.dispatches.find((d) => d.dispatch_id === 'dsp_003')!.status).toBe('cancelled')
    expect(snap.dispatches.find((d) => d.dispatch_id === 'dsp_001')!.status).toBe('delivered')
  })

  it('sendText appends an outgoing message', async () => {
    const src = createMockSource({ drift: false })
    await src.sendText('603-555-0123', 'Water on the way')
    const snap = await src.getSnapshot()
    expect(snap.messages.at(-1)).toMatchObject({ direction: 'out', body: 'Water on the way' })
  })
})

describe('mock drift', () => {
  it('jitters every simulated headcount within ±5% and keeps it fresh', async () => {
    let now = Date.parse('2026-01-01T00:00:00Z')
    const src = createMockSource({ seed: 7, clock: () => now })
    for (let i = 0; i < 20; i++) {
      now += 3000
      const snap = await src.getSnapshot()
      const s1 = snap.peopleCounts.find((c) => c.camera_id === 'sim_s1')!.people_count
      expect(s1).toBeGreaterThanOrEqual(209)
      expect(s1).toBeLessThanOrEqual(231)
      const s4 = snap.peopleCounts.find((c) => c.camera_id === 'sim_s4')!
      expect(s4.people_count).toBeGreaterThanOrEqual(85)
      expect(s4.people_count).toBeLessThanOrEqual(95)
      expect(Date.parse(s4.timestamp)).toBe(now)
    }
  })

  it('never pushes a site over 90% capacity by noise alone', async () => {
    const src = createMockSource({ seed: 3 })
    for (let i = 0; i < 50; i++) {
      const snap = await src.getSnapshot()
      expect(snap.peopleCounts.find((c) => c.camera_id === 'sim_s3')!.people_count).toBeLessThanOrEqual(180)
    }
  })

  it('consumes water at occupied shelters and adds incoming texts over time', async () => {
    const src = createMockSource({ seed: 1 })
    const before = await src.getSnapshot()
    let after = before
    for (let i = 0; i < 40; i++) after = await src.getSnapshot()
    expect(qty(after, 'shelter_1', 'water_L')!).toBeLessThan(qty(before, 'shelter_1', 'water_L')!)
    expect(after.messages.length).toBeGreaterThan(before.messages.length)
  })

  it('the demo event raises Shelter 3 headcount and reports low water', async () => {
    const src = createMockSource({ drift: false })
    src.triggerDemoEvent()
    const snap = await src.getSnapshot()
    expect(snap.peopleCounts.find((c) => c.camera_id === 'sim_s3')!.people_count).toBe(176)
    expect(qty(snap, 'shelter_3', 'water_L')).toBe(60)
    expect(snap.messages.at(-1)!.parsed).toMatchObject({ site_id: 'shelter_3', item: 'water_L', quantity: 60 })
  })
})

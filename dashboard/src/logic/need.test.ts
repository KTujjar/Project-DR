import { describe, expect, it } from 'vitest'
import { computeNeed, itemStatus, latestStock } from './need'

describe('computeNeed', () => {
  it('applies per-person rates over 24 hours', () => {
    expect(computeNeed(100, 300)).toEqual({ water_L: 300, food_meals: 300, medical_kits: 2, blankets: 100, cots: 100 })
  })

  it('rounds medical kits up', () => {
    expect(computeNeed(51).medical_kits).toBe(2)
    expect(computeNeed(1).medical_kits).toBe(1)
    expect(computeNeed(0).medical_kits).toBe(0)
  })

  it('caps cots at shelter capacity', () => {
    expect(computeNeed(250, 200).cots).toBe(200)
  })
})

describe('itemStatus', () => {
  it('computes shortfall and coverage', () => {
    expect(itemStatus(500, 120)).toEqual({ need: 500, onHand: 120, shortfall: 380, coverage: 0.24 })
    expect(itemStatus(100, 150)).toMatchObject({ shortfall: 0, coverage: 1.5 })
    expect(itemStatus(0, 0).coverage).toBe(1)
  })
})

describe('latestStock', () => {
  it('keeps the most recent record per site and item', () => {
    const stock = latestStock([
      { site_id: 's1', item: 'water_L', quantity: 10, source: 'sms', timestamp: '2026-01-01T00:02:00Z' },
      { site_id: 's1', item: 'water_L', quantity: 99, source: 'sms', timestamp: '2026-01-01T00:01:00Z' },
      { site_id: 's1', item: 'cots', quantity: 5, source: 'manual', timestamp: '2026-01-01T00:00:00Z' },
    ])
    expect(stock.s1.water_L).toBe(10)
    expect(stock.s1.cots).toBe(5)
    expect(stock.s1.blankets).toBe(0)
  })
})

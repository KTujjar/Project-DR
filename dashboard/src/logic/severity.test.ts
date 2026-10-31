import { describe, expect, it } from 'vitest'
import { itemStatuses } from './need'
import { severityFromCoverage, siteSeverity } from './severity'

const covered = { water_L: 100, food_meals: 100, medical_kits: 2, blankets: 100, cots: 100 }

describe('severityFromCoverage', () => {
  it('maps coverage bands', () => {
    expect(severityFromCoverage(1)).toBe('ok')
    expect(severityFromCoverage(0.99)).toBe('low')
    expect(severityFromCoverage(0.5)).toBe('low')
    expect(severityFromCoverage(0.49)).toBe('critical')
  })
})

describe('siteSeverity', () => {
  it('uses the worst item', () => {
    const items = itemStatuses(covered, { ...covered, water_L: 30 })
    expect(siteSeverity(items, 50, 200)).toEqual({ severity: 'critical', worstItem: 'water_L', overCapacity: false })
  })

  it('is OK with no worst item when everything is covered', () => {
    const items = itemStatuses(covered, covered)
    expect(siteSeverity(items, 50, 200)).toEqual({ severity: 'ok', worstItem: null, overCapacity: false })
  })

  it('is Critical above 90% capacity even when stocked', () => {
    const items = itemStatuses(covered, covered)
    expect(siteSeverity(items, 181, 200)).toMatchObject({ severity: 'critical', overCapacity: true })
    expect(siteSeverity(items, 180, 200)).toMatchObject({ severity: 'ok', overCapacity: false })
  })
})

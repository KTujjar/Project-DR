import { describe, expect, it } from 'vitest'
import { haversineKm } from './geo'
import { etaMinutes } from './suggestions'

describe('haversineKm', () => {
  it('is zero for the same point', () => {
    expect(haversineKm({ lat: 43.7, lng: -72.3 }, { lat: 43.7, lng: -72.3 })).toBe(0)
  })

  it('measures one degree of latitude as about 111 km', () => {
    expect(haversineKm({ lat: 43, lng: -72 }, { lat: 44, lng: -72 })).toBeCloseTo(111.2, 0)
  })
})

describe('etaMinutes', () => {
  it('assumes 40 km/h and never returns 0', () => {
    expect(etaMinutes(20)).toBe(30)
    expect(etaMinutes(0)).toBe(1)
  })
})


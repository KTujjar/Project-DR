import { describe, expect, it } from 'vitest'
import type { PeopleCount } from '../types/schemas'
import { siteHeadcounts, trend } from './headcount'

const pc = (camera_id: string, site_id: string, people_count: number, timestamp: string): PeopleCount => ({
  camera_id, site_id, people_count, timestamp, confidence: 0.9,
})

describe('siteHeadcounts', () => {
  const counts = [
    pc('a', 's1', 100, '2026-01-01T00:00:00Z'),
    pc('a', 's1', 120, '2026-01-01T00:01:00Z'), // newer reading from the same camera
    pc('b', 's1', 30, '2026-01-01T00:01:00Z'),
    pc('c', 's2', 50, '2026-01-01T00:01:00Z'),
  ]

  it('sums the latest count of each camera per site', () => {
    expect(siteHeadcounts(counts, 'sum')).toEqual({ s1: 150, s2: 50 })
  })

  it('takes the max when cameras overlap', () => {
    expect(siteHeadcounts(counts, 'max')).toEqual({ s1: 120, s2: 50 })
  })
})

describe('trend', () => {
  it('compares against the previous headcount', () => {
    expect(trend(undefined, 10)).toBe('flat')
    expect(trend(10, 10)).toBe('flat')
    expect(trend(10, 12)).toBe('up')
    expect(trend(10, 8)).toBe('down')
  })
})


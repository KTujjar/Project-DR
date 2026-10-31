import { describe, expect, it } from 'vitest'
import { aidsSummary, flowLabel, gridCellColor, isStatsStale, peopleLabel, percent, speedLabel } from './crowdStats'

describe('crowd stats formatting', () => {
  it('marks lower-bound people counts', () => {
    expect(peopleLabel({ people: 15, people_is_lower_bound: true })).toBe('≥ 15')
    expect(peopleLabel({ people: 3, people_is_lower_bound: false })).toBe('3')
  })

  it('formats fractions and missing values', () => {
    expect(percent(0.456)).toBe('46%')
    expect(percent(null)).toBe('–')
    expect(speedLabel(0.4567)).toBe('0.46 body-heights/s')
    expect(speedLabel(null)).toBe('–')
  })

  it('summarises mobility aids', () => {
    expect(aidsSummary(null)).toBe('detector off')
    expect(aidsSummary({ wheelchair: 0, cane: 0 })).toBe('none visible')
    expect(aidsSummary({ wheelchair: 1, cane: 2, crutches: 1 })).toBe('1 wheelchair, 2 canes, 1 crutches')
  })

  it('describes flow', () => {
    expect(flowLabel({ dominant_flow: null, flow_coherence: null, counterflow: false })).toBe('–')
    expect(flowLabel({ dominant_flow: 'right', flow_coherence: 0.9, counterflow: true })).toBe(
      'right (90% aligned), counterflow',
    )
  })

  it('flags stats older than 10 s as stale', () => {
    expect(isStatsStale(1000, 1_005_000)).toBe(false)
    expect(isStatsStale(1000, 1_011_000)).toBe(true)
  })

  it('colors empty, busy and over-capacity grid cells', () => {
    expect(gridCellColor(0)).toBe('rgba(148, 163, 184, 0.08)')
    expect(gridCellColor(0.75)).toBe('hsla(23, 90%, 50%, 0.57)')
    expect(gridCellColor(3)).toBe(gridCellColor(1.5))
  })
})

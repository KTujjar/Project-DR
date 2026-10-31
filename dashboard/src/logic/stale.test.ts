import { describe, expect, it } from 'vitest'
import { createScenario } from '../data/mock/scenario'
import { staleSources } from './stale'

describe('staleSources', () => {
  const now = Date.parse('2026-01-01T00:00:00Z')
  const snap = createScenario(now)

  it('reports nothing for fresh data', () => {
    expect(staleSources(snap, now)).toEqual([])
  })

  it('uses the newest record, so one old camera does not make the feed stale', () => {
    // The seeded offline camera's last frame is 14 minutes old.
    expect(staleSources(snap, now + 30_000)).toEqual([])
  })

  it('flags every feed once its newest record is older than 60 s', () => {
    const stale = staleSources(snap, now + 90_000)
    expect(stale.map((s) => s.source).sort()).toEqual(['cameras', 'inventory', 'people counts'])
    expect(stale.find((s) => s.source === 'cameras')!.ageSeconds).toBe(90)
  })
})


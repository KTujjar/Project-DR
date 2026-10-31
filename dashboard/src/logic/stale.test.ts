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
    const cameras = [
      { camera_id: 'old', site_id: 'shelter_1', online: false, last_frame_at: new Date(now - 14 * 60_000).toISOString() },
      { camera_id: 'new', site_id: 'shelter_2', online: true, last_frame_at: new Date(now).toISOString() },
    ]
    expect(staleSources({ ...snap, cameras }, now + 30_000)).toEqual([])
  })

  it('flags every feed once its newest record is older than 60 s', () => {
    const stale = staleSources(snap, now + 90_000)
    // The mock has no cameras, so there is no camera feed to go stale.
    expect(stale.map((s) => s.source).sort()).toEqual(['inventory', 'people counts'])
    expect(stale.find((s) => s.source === 'people counts')!.ageSeconds).toBe(90)
    const withCamera = { ...snap, cameras: [{ camera_id: 'c', site_id: 'shelter_1', online: true, last_frame_at: new Date(now).toISOString() }] }
    expect(staleSources(withCamera, now + 90_000).find((s) => s.source === 'cameras')!.ageSeconds).toBe(90)
  })
})

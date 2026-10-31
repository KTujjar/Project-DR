import { describe, expect, it, vi } from 'vitest'
import type { CameraFeed, DataSource, PeopleCount } from '../../types/schemas'
import { createScenario } from '../mock/scenario'
import { withCvOverlay } from './cvOverlay'

const CV_CAMERA: CameraFeed = {
  camera_id: 'cam_s3',
  site_id: 'shelter_3',
  stream_url: 'http://cv:8001/api/cameras/cam_s3/stream.mjpg',
  snapshot_url: 'http://cv:8001/api/cameras/cam_s3/snapshot.jpg?t=1',
  online: true,
  last_frame_at: '2026-10-30T22:40:01.000Z',
}
const CV_COUNT: PeopleCount = {
  site_id: 'shelter_3', camera_id: 'cam_s3', timestamp: '2026-10-30T22:40:01.000Z', people_count: 2, confidence: 0.8,
}

function baseSource(): DataSource {
  const snapshot = createScenario(0)
  return {
    getSnapshot: vi.fn(async () => structuredClone(snapshot)),
    approveDispatch: vi.fn(async () => {}),
    cancelDispatch: vi.fn(async () => {}),
    createDispatch: vi.fn(async () => {}),
    sendText: vi.fn(async () => {}),
  }
}

function cvFetch(ok = true) {
  return vi.fn(async (url: string | URL | Request) => {
    if (!ok) throw new TypeError('Failed to fetch')
    const body = String(url).endsWith('/api/cameras') ? [CV_CAMERA] : [CV_COUNT]
    return new Response(JSON.stringify(body), { status: 200 })
  })
}

describe('withCvOverlay', () => {
  it('replaces only the CV-owned camera and its counts', async () => {
    const f = cvFetch()
    const snap = await withCvOverlay(baseSource(), 'http://cv:8001/', f).getSnapshot()

    expect(f).toHaveBeenCalledWith('http://cv:8001/api/cameras')
    expect(f).toHaveBeenCalledWith('http://cv:8001/api/people-counts')
    expect(snap.cameras.filter((c) => c.camera_id === 'cam_s3')).toEqual([CV_CAMERA])
    expect(snap.peopleCounts.filter((p) => p.camera_id === 'cam_s3')).toEqual([CV_COUNT])
    // Other cameras still come from the base source.
    expect(snap.cameras.map((c) => c.camera_id).sort()).toEqual(['cam_s1', 'cam_s2', 'cam_s3', 'cam_s4'])
    expect(snap.peopleCounts.find((p) => p.camera_id === 'cam_s1')?.people_count).toBe(220)
    expect(snap.locations).toHaveLength(7)
  })

  it('keeps the last good CV data when the service goes down', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    let up = true
    const f = vi.fn(async (url: string | URL | Request) => (up ? cvFetch()(url) : cvFetch(false)(url)))
    const src = withCvOverlay(baseSource(), 'http://cv:8001', f)

    await src.getSnapshot()
    up = false
    const snap = await src.getSnapshot()
    await src.getSnapshot()

    expect(snap.cameras.find((c) => c.camera_id === 'cam_s3')).toEqual(CV_CAMERA)
    expect(warn).toHaveBeenCalledTimes(1)
    warn.mockRestore()
  })

  it('falls back to the base snapshot if the CV service was never reachable', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const base = baseSource()
    const snap = await withCvOverlay(base, 'http://cv:8001', cvFetch(false)).getSnapshot()
    expect(snap).toEqual(await base.getSnapshot())
    warn.mockRestore()
  })

  it('delegates actions to the base source', async () => {
    const base = baseSource()
    const src = withCvOverlay(base, 'http://cv:8001', cvFetch())
    const dispatch = createScenario(0).dispatches[0]
    await src.approveDispatch('a')
    await src.cancelDispatch('b')
    await src.createDispatch(dispatch)
    await src.sendText('603-555-0101', 'hi')
    expect(base.approveDispatch).toHaveBeenCalledWith('a')
    expect(base.cancelDispatch).toHaveBeenCalledWith('b')
    expect(base.createDispatch).toHaveBeenCalledWith(dispatch)
    expect(base.sendText).toHaveBeenCalledWith('603-555-0101', 'hi')
  })
})

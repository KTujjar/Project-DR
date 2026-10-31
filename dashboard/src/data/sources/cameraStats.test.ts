import { describe, expect, it, vi } from 'vitest'
import { fetchCameraStats } from './cameraStats'

const PASS = { camera_id: 'cam_s3', in_pass: false, managed: true, running_count: 4, last_pass_count: 4, passes_completed: 1 }

function fakeFetch(statsStatus: number, statsBody: unknown, passStatus = 200) {
  return vi.fn(async (url: string | URL | Request) => {
    const isStats = String(url).endsWith('/stats')
    const status = isStats ? statsStatus : passStatus
    return new Response(JSON.stringify(isStats ? statsBody : PASS), { status, statusText: status === 200 ? 'OK' : 'Error' })
  })
}

describe('fetchCameraStats', () => {
  it('returns the stats and pass status for a CV camera', async () => {
    const f = fakeFetch(200, { people: 4 })
    const res = await fetchCameraStats('http://cv:8001/', 'cam s3', f)
    expect(res).toEqual({ stats: { people: 4 }, pass: PASS })
    expect(f).toHaveBeenCalledWith('http://cv:8001/api/cameras/cam%20s3/stats')
    expect(f).toHaveBeenCalledWith('http://cv:8001/api/cameras/cam%20s3/pass')
  })

  it('returns null before the first measurement', async () => {
    expect((await fetchCameraStats('http://cv', 'cam_s3', fakeFetch(200, null))).stats).toBeNull()
  })

  it("reports 'unavailable' for cameras the CV service doesn't have", async () => {
    expect(await fetchCameraStats('http://cv', 'cam_s2', fakeFetch(404, {}, 404))).toEqual({ stats: 'unavailable', pass: null })
  })

  it('throws when the service errors or is unreachable', async () => {
    await expect(fetchCameraStats('http://cv', 'cam_s3', fakeFetch(500, {}))).rejects.toThrow(/500/)
    const down = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    })
    await expect(fetchCameraStats('http://cv', 'cam_s3', down)).rejects.toThrow('Failed to fetch')
  })

  it('still returns stats when the pass status is missing', async () => {
    expect((await fetchCameraStats('http://cv', 'cam_s3', fakeFetch(200, { people: 1 }, 404))).pass).toBeNull()
  })
})

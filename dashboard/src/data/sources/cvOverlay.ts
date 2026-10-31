import type { CameraFeed, DashboardSnapshot, DataSource, PeopleCount } from '../../types/schemas'

interface CvData {
  cameras: CameraFeed[]
  peopleCounts: PeopleCount[]
}

// Adds live cameras and people counts from the CV service (relief-vision/); everything else
// comes from the base source. Once a real camera has counted people at a shelter, it owns that
// shelter's headcount: the base source's counts there (e.g. the mock's simulated ones) are dropped
// so they aren't added on top. A camera that hasn't reported yet (phone not connected) leaves
// the simulated count in place.
export function mergeCv(base: DashboardSnapshot, cv: CvData): DashboardSnapshot {
  const cvIds = new Set(cv.cameras.map((c) => c.camera_id))
  const cvSites = new Set(cv.peopleCounts.map((p) => p.site_id))
  return {
    ...base,
    cameras: [...base.cameras.filter((c) => !cvIds.has(c.camera_id)), ...cv.cameras],
    peopleCounts: [
      ...base.peopleCounts.filter((p) => !cvIds.has(p.camera_id) && !cvSites.has(p.site_id)),
      ...cv.peopleCounts,
    ],
  }
}

// If the CV service is unreachable, the last good CV data is reused with its cameras marked offline,
// so they grey out and their timestamps age into the stale-data warning instead of the snapshot failing.
export function withCvOverlay(base: DataSource, cvUrl: string, fetchImpl: typeof fetch = (...args) => fetch(...args)): DataSource {
  const root = cvUrl.replace(/\/+$/, '')
  let lastGood: CvData | null = null
  let warned = false

  async function getJson<T>(path: string): Promise<T> {
    const res = await fetchImpl(`${root}${path}`)
    if (!res.ok) throw new Error(`GET ${path} failed: ${res.status} ${res.statusText}`)
    return (await res.json()) as T
  }

  async function fetchCv(): Promise<CvData | null> {
    try {
      const [cameras, peopleCounts] = await Promise.all([
        getJson<CameraFeed[]>('/api/cameras'),
        getJson<PeopleCount[]>('/api/people-counts'),
      ])
      lastGood = { cameras, peopleCounts }
      warned = false
      return lastGood
    } catch (err) {
      if (!warned) console.warn('CV service unreachable, keeping last camera data', err)
      warned = true
      return lastGood && { ...lastGood, cameras: lastGood.cameras.map((c) => ({ ...c, online: false })) }
    }
  }

  return {
    async getSnapshot() {
      const [snapshot, cv] = await Promise.all([base.getSnapshot(), fetchCv()])
      return cv ? mergeCv(snapshot, cv) : snapshot
    },
    approveDispatch: (id) => base.approveDispatch(id),
    cancelDispatch: (id) => base.cancelDispatch(id),
    createDispatch: (dispatch) => base.createDispatch(dispatch),
    sendText: (phone, body) => base.sendText(phone, body),
  }
}

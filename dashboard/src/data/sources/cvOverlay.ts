import type { CameraFeed, DashboardSnapshot, DataSource, PeopleCount } from '../../types/schemas'

interface CvData {
  cameras: CameraFeed[]
  peopleCounts: PeopleCount[]
}

// Replaces cameras and people counts with live ones from the CV service (cv/ on Khaled-cv);
// everything else comes from the base source. Cameras the CV doesn't own keep their base data.
export function mergeCv(base: DashboardSnapshot, cv: CvData): DashboardSnapshot {
  const cvIds = new Set(cv.cameras.map((c) => c.camera_id))
  return {
    ...base,
    cameras: [...base.cameras.filter((c) => !cvIds.has(c.camera_id)), ...cv.cameras],
    peopleCounts: [...base.peopleCounts.filter((p) => !cvIds.has(p.camera_id)), ...cv.peopleCounts],
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

import type { CrowdStats, PassStatus } from '../../types/crowdStats'

// 'unavailable': the CV service has no metrics for this camera (e.g. a mock camera).
// null: the camera exists but hasn't produced its first measurement yet.
export type StatsResult = CrowdStats | null | 'unavailable'

export interface CameraStatsResponse {
  stats: StatsResult
  pass: PassStatus | null
}

const cameraRoot = (cvUrl: string, cameraId: string) =>
  `${cvUrl.replace(/\/+$/, '')}/api/cameras/${encodeURIComponent(cameraId)}`

// Fetches one camera's crowd metrics and pass status from the CV service.
// Throws when the service is unreachable or errors, so the caller can keep showing the last values.
export async function fetchCameraStats(
  cvUrl: string,
  cameraId: string,
  fetchImpl: typeof fetch = (...args) => fetch(...args),
): Promise<CameraStatsResponse> {
  const root = cameraRoot(cvUrl, cameraId)
  const [statsRes, passRes] = await Promise.all([fetchImpl(`${root}/stats`), fetchImpl(`${root}/pass`)])
  if (statsRes.status === 404) return { stats: 'unavailable', pass: null }
  if (!statsRes.ok) throw new Error(`GET stats failed: ${statsRes.status} ${statsRes.statusText}`)
  return {
    stats: (await statsRes.json()) as CrowdStats | null,
    pass: passRes.ok ? ((await passRes.json()) as PassStatus) : null,
  }
}

// Marks the start or end of a pass along a line (robot or phone sweep). Ending a pass publishes its
// unique-people total as the camera's count. Returns the new pass status; throws on failure.
async function passAction(
  action: 'start' | 'end',
  cvUrl: string,
  cameraId: string,
  fetchImpl: typeof fetch = (...args) => fetch(...args),
): Promise<PassStatus> {
  const res = await fetchImpl(`${cameraRoot(cvUrl, cameraId)}/pass/${action}`, { method: 'POST' })
  if (!res.ok) throw new Error(`Pass ${action} failed: ${res.status} ${res.statusText}`)
  return (await res.json()) as PassStatus
}

export const startPass = (cvUrl: string, cameraId: string, fetchImpl?: typeof fetch) =>
  passAction('start', cvUrl, cameraId, fetchImpl)
export const endPass = (cvUrl: string, cameraId: string, fetchImpl?: typeof fetch) =>
  passAction('end', cvUrl, cameraId, fetchImpl)

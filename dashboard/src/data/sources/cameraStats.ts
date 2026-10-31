import type { CrowdStats, PassStatus } from '../../types/crowdStats'

// 'unavailable': the CV service has no metrics for this camera (e.g. a mock camera).
// null: the camera exists but hasn't produced its first measurement yet.
export type StatsResult = CrowdStats | null | 'unavailable'

export interface CameraStatsResponse {
  stats: StatsResult
  pass: PassStatus | null
}

// Fetches one camera's crowd metrics and pass status from the CV service.
// Throws when the service is unreachable or errors, so the caller can keep showing the last values.
export async function fetchCameraStats(
  cvUrl: string,
  cameraId: string,
  fetchImpl: typeof fetch = (...args) => fetch(...args),
): Promise<CameraStatsResponse> {
  const root = `${cvUrl.replace(/\/+$/, '')}/api/cameras/${encodeURIComponent(cameraId)}`
  const [statsRes, passRes] = await Promise.all([fetchImpl(`${root}/stats`), fetchImpl(`${root}/pass`)])
  if (statsRes.status === 404) return { stats: 'unavailable', pass: null }
  if (!statsRes.ok) throw new Error(`GET stats failed: ${statsRes.status} ${statsRes.statusText}`)
  return {
    stats: (await statsRes.json()) as CrowdStats | null,
    pass: passRes.ok ? ((await passRes.json()) as PassStatus) : null,
  }
}

// Crowd metrics for one camera, as served by the CV service (reliefvision `Event`, schema 0.1)
// at GET {VITE_CV_API_URL}/api/cameras/{id}/stats. CV-specific, so it lives outside the shared
// schemas.ts contracts; the dashboard only fetches it while a camera's enlarged view is open.

export type Density = 'low' | 'medium' | 'high' | 'packed'
export type MobilityAid = 'wheelchair' | 'walker' | 'crutches' | 'cane' | 'stroller'

export interface Hotspot {
  region: string // camera-relative, e.g. "bottom-left"
  row: number
  col: number
  score: number // 0..1, crowded AND barely moving
}

export interface Insight {
  level: 'info' | 'warn'
  code: string
  message: string
}

export interface CrowdStats {
  schema_version: string
  site_id: string
  camera_id: string
  ts: number // epoch seconds
  pose?: string | null
  camera_mode: 'fixed' | 'mobile' // mobile => movement and space metrics are null
  people: number
  people_is_lower_bound: boolean
  density: Density
  crowd_fraction: number
  children_est: number | null
  mobility_aids: Partial<Record<MobilityAid, number>> | null // null = detector off
  avg_speed_bh_s: number | null // body-heights per second (walking ~1)
  stationary_fraction: number | null
  stagnation_index: number | null
  dominant_flow: string | null
  flow_coherence: number | null
  counterflow: boolean
  free_space_fraction: number | null
  grid_rows: number
  grid_cols: number
  crowd_grid: number[][] // 0..1.5 per cell, 1 = at capacity
  hotspots: Hotspot[]
  insights: Insight[]
}

// Pass counting for the same camera (GET /api/cameras/{id}/pass).
export interface PassStatus {
  camera_id: string
  in_pass: boolean
  managed: boolean
  running_count: number
  last_pass_count: number | null
  passes_completed: number
}

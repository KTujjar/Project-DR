import { useEffect, useState, type ReactNode } from 'react'
import { fetchCameraStats, type CameraStatsResponse } from '../../data/sources/cameraStats'
import {
  aidsSummary,
  flowLabel,
  gridCellColor,
  isStatsStale,
  peopleLabel,
  percent,
  speedLabel,
} from '../../logic/crowdStats'
import type { CrowdStats, Density, PassStatus } from '../../types/crowdStats'
import { timeAgo } from '../labels'

const POLL_MS = 2000 // the CV service emits new metrics every 2 s

const DENSITY_CLASS: Record<Density, string> = {
  low: 'bg-green-900 text-green-200',
  medium: 'bg-yellow-900 text-yellow-200',
  high: 'bg-orange-900 text-orange-200',
  packed: 'bg-red-900 text-red-200',
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-slate-700 pt-2">
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</h3>
      {children}
    </section>
  )
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex justify-between gap-3 text-sm">
      <span className="text-slate-400">{label}</span>
      <span className="text-right font-medium text-slate-100">{value}</span>
    </div>
  )
}

function PassRows({ pass }: { pass: PassStatus | null }) {
  if (!pass) return <p className="text-sm text-slate-400">Not available.</p>
  return (
    <>
      <Row label="Current pass" value={pass.in_pass ? `${pass.running_count} counted so far` : 'not running'} />
      <Row label="Last full pass" value={pass.last_pass_count ?? '–'} />
    </>
  )
}

function CrowdGrid({ stats }: { stats: CrowdStats }) {
  return (
    <div
      className="mt-1 grid gap-px overflow-hidden rounded"
      style={{ gridTemplateColumns: `repeat(${stats.grid_cols}, minmax(0, 1fr))` }}
      aria-label="Crowding by area of the camera view"
    >
      {stats.crowd_grid.flatMap((row, r) =>
        row.map((v, c) => (
          <div key={`${r}-${c}`} className="h-3" style={{ background: gridCellColor(v) }} title={`${Math.round(v * 100)}%`} />
        )),
      )}
    </div>
  )
}

function StatsBody({ stats, pass }: { stats: CrowdStats; pass: PassStatus | null }) {
  const fixed = stats.camera_mode === 'fixed'
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <span className="text-3xl font-bold text-slate-100">{peopleLabel(stats)}</span>
        <span className={`rounded px-1.5 py-0.5 text-xs font-semibold uppercase ${DENSITY_CLASS[stats.density]}`}>
          {stats.density}
        </span>
      </div>
      <p className="text-xs text-slate-400">
        people in view · {percent(stats.crowd_fraction)} of frame covered · {stats.camera_mode} camera
      </p>

      <Section title="Who may need help">
        <Row label="Children (rough)" value={stats.children_est ?? 'calibrating…'} />
        <Row label="Mobility aids" value={aidsSummary(stats.mobility_aids)} />
      </Section>

      <Section title="Movement">
        {fixed ? (
          <>
            <Row label="Average speed" value={speedLabel(stats.avg_speed_bh_s)} />
            <Row label="Standing still" value={percent(stats.stationary_fraction)} />
            <Row label="Flow" value={flowLabel(stats)} />
          </>
        ) : (
          <p className="text-sm text-slate-400">Needs a steady camera (moving now).</p>
        )}
      </Section>

      <Section title="Space">
        {fixed ? (
          <>
            <Row label="Stagnation" value={percent(stats.stagnation_index)} />
            <Row label="Free space" value={percent(stats.free_space_fraction)} />
            <Row label="Hotspots" value={stats.hotspots.map((h) => h.region).join(', ') || 'none'} />
          </>
        ) : (
          <p className="text-sm text-slate-400">Needs a steady camera (moving now).</p>
        )}
        <CrowdGrid stats={stats} />
      </Section>

      <Section title="Line count (passes)">
        <PassRows pass={pass} />
      </Section>

      {stats.insights.length > 0 && (
        <Section title="Insights">
          <ul className="space-y-1">
            {stats.insights.map((ins) => (
              <li
                key={ins.code + ins.message}
                className={`rounded px-2 py-1 text-xs ${ins.level === 'warn' ? 'bg-amber-900/60 text-amber-100' : 'bg-slate-800 text-slate-300'}`}
              >
                {ins.message}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  )
}

// Live crowd metrics for one camera, fetched from the CV service while the enlarged view is open.
export function CameraStats({ cameraId, cvUrl }: { cameraId: string; cvUrl: string }) {
  const [data, setData] = useState<CameraStatsResponse | null>(null)
  const [unreachable, setUnreachable] = useState(false)

  // Rendered with key={cameraId}, so switching cameras starts from a fresh, empty state.
  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const res = await fetchCameraStats(cvUrl, cameraId)
        if (!cancelled) {
          setData(res)
          setUnreachable(false)
        }
      } catch {
        if (!cancelled) setUnreachable(true) // keep the last values on screen
      }
    }
    void load()
    const timer = setInterval(load, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [cameraId, cvUrl])

  const stats = data && data.stats !== 'unavailable' ? data.stats : null
  let body: ReactNode
  if (!data) body = <p className="text-sm text-slate-400">{unreachable ? 'CV service unreachable.' : 'Loading metrics…'}</p>
  else if (data.stats === 'unavailable') body = <p className="text-sm text-slate-400">No live metrics for this camera (mock data).</p>
  else if (data.stats === null)
    body = (
      <div className="space-y-2">
        <p className="text-sm text-slate-400">Waiting for first measurements…</p>
        <Section title="Line count (passes)">
          <PassRows pass={data.pass} />
        </Section>
      </div>
    )
  else body = <StatsBody stats={data.stats} pass={data.pass} />

  const stale = unreachable || (stats !== null && isStatsStale(stats.ts))
  return (
    <aside className="w-full rounded-lg bg-slate-900 p-3 text-slate-200 md:w-80" aria-label={`Crowd metrics for ${cameraId}`}>
      <header className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-300">Crowd metrics</h2>
        {stats && (
          <span className="text-xs text-slate-400">Updated {timeAgo(new Date(stats.ts * 1000).toISOString())}</span>
        )}
      </header>
      {data && unreachable && <p className="mb-2 rounded bg-red-900/60 px-2 py-1 text-xs text-red-100">CV service unreachable. Showing last values.</p>}
      <div className={stale ? 'opacity-50' : ''}>{body}</div>
    </aside>
  )
}

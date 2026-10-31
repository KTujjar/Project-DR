import { useEffect, useState } from 'react'
import type { Issue } from '../../logic/priority'
import { staleSources } from '../../logic/stale'
import { useDashboardStore } from '../../store/useDashboardStore'

const NO_ISSUES: Issue[] = []
const TOP_N = 3

const ISSUE_CLASS = {
  critical: 'bg-red-600 text-white hover:bg-red-700',
  low: 'bg-yellow-400 text-slate-900 hover:bg-yellow-300',
  ok: 'bg-slate-700 text-white',
}

const KIND_ICON = { shortfall: '⚠', capacity: '⚠', needs_review: '✉', camera_offline: '📷' }

function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}

function ThemeToggle() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))
  const toggle = () => {
    const next = !dark
    document.documentElement.classList.toggle('dark', next)
    try {
      localStorage.setItem('theme', next ? 'dark' : 'light')
    } catch {
      // Storage unavailable: the choice just won't persist.
    }
    setDark(next)
  }
  return (
    <button
      type="button"
      onClick={toggle}
      title={dark ? 'Switch to light theme' : 'Switch to dark theme'}
      aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'}
      className="rounded px-1.5 py-0.5 text-sm text-slate-300 hover:bg-slate-700"
    >
      {dark ? '☀' : '☾'}
    </button>
  )
}

export function AlertsBar() {
  const priorities = useDashboardStore((s) => s.derived?.priorities ?? NO_ISSUES)
  const snapshot = useDashboardStore((s) => s.snapshot)
  const lastFetchAt = useDashboardStore((s) => s.lastFetchAt)
  const connectionLost = useDashboardStore((s) => s.connectionLost)
  const selectSite = useDashboardStore((s) => s.selectSite)
  const selectedSiteId = useDashboardStore((s) => s.selectedSiteId)
  const now = useNow()
  const selectedName = snapshot?.locations.find((l) => l.id === selectedSiteId)?.name

  const top = priorities.slice(0, TOP_N)
  const more = priorities.length - top.length
  const stale = snapshot ? staleSources(snapshot, now) : []
  const fetchAge = lastFetchAt ? Math.max(0, Math.round((now - lastFetchAt) / 1000)) : null

  return (
    <header className="rounded-lg bg-slate-900 px-3 py-2 text-white dark:border dark:border-slate-700">
      {connectionLost && (
        <div className="mb-2 rounded bg-red-600 px-2 py-1 text-sm font-semibold">
          Connection lost. Showing last good data{fetchAge !== null ? ` from ${fetchAge}s ago` : ''}, retrying...
        </div>
      )}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="whitespace-nowrap">
          <span className="font-semibold">Project-DR</span> <span className="text-slate-400">Coordinator</span>
        </div>

        <ol className="flex min-w-0 flex-1 flex-wrap gap-2 overflow-hidden lg:flex-nowrap">
          {top.length === 0 && <li className="text-sm text-green-400">No urgent issues</li>}
          {top.map((issue, i) => (
            <li key={issue.id} className="min-w-0">
              <button
                type="button"
                onClick={() => issue.site_id && selectSite(issue.site_id)}
                title={issue.title}
                className={`block w-full max-w-[19rem] truncate rounded px-2 py-1 text-left text-xs font-medium ${ISSUE_CLASS[issue.severity]} ${
                  issue.site_id && issue.site_id === selectedSiteId ? 'ring-2 ring-sky-300' : ''
                }`}
              >
                {i + 1}. {KIND_ICON[issue.kind]} {issue.title}
              </button>
            </li>
          ))}
          {more > 0 && (
            <li
              className="shrink-0 self-center whitespace-nowrap text-xs text-slate-400"
              title={priorities.slice(TOP_N).map((i) => i.title).join('\n')}
            >
              +{more} more
            </li>
          )}
        </ol>

        <div className="flex items-center gap-3 whitespace-nowrap text-xs">
          {selectedName && (
            <button
              type="button"
              onClick={() => selectSite(null)}
              title="Clear selection (Esc)"
              className="rounded bg-sky-600 px-2 py-1 font-medium hover:bg-sky-500"
            >
              Selected: {selectedName} ✕
            </button>
          )}
          {stale.length > 0 ? (
            <span className="rounded bg-amber-500 px-2 py-1 font-semibold text-slate-900" title="No new data for over 60 s">
              Stale: {stale.map((s) => `${s.source} (${s.ageSeconds}s)`).join(', ')}
            </span>
          ) : (
            <span className="text-slate-400">
              <span className={`mr-1 inline-block h-2 w-2 rounded-full ${connectionLost ? 'bg-red-500' : 'bg-green-500'}`} />
              {fetchAge === null ? 'Loading...' : `Updated ${fetchAge}s ago`}
            </span>
          )}
          <time className="font-mono text-sm tabular-nums">{new Date(now).toLocaleTimeString()}</time>
          <ThemeToggle />
        </div>
      </div>
    </header>
  )
}

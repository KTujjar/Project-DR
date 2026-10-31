import { useState } from 'react'
import { useDashboardStore } from '../../store/useDashboardStore'
import type { Dispatch, DispatchStatus } from '../../types/schemas'
import { formatItems } from '../labels'
import { Panel } from '../Panel'

const NO_DISPATCHES: Dispatch[] = []

const GROUPS: { status: DispatchStatus; label: string }[] = [
  { status: 'suggested', label: 'Suggested' },
  { status: 'pending', label: 'Pending' },
  { status: 'en_route', label: 'En route' },
  { status: 'delivered', label: 'Delivered' },
  { status: 'cancelled', label: 'Cancelled' },
]

const STATUS_CLASS: Record<DispatchStatus, string> = {
  suggested: 'border-sky-300 dark:border-sky-700 bg-sky-50 dark:bg-sky-950',
  pending: 'border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950/50',
  en_route: 'border-blue-300 dark:border-blue-700 bg-white dark:bg-slate-900',
  delivered: 'border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-500 dark:text-slate-400',
  cancelled: 'border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-400 line-through',
}

function Button({ onClick, children, variant }: { onClick: () => void; children: string; variant: 'primary' | 'plain' }) {
  const cls =
    variant === 'primary'
      ? 'bg-green-600 text-white hover:bg-green-700'
      : 'border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700'
  return (
    <button type="button" onClick={onClick} className={`rounded px-2 py-0.5 text-xs font-medium ${cls}`}>
      {children}
    </button>
  )
}

export function DispatchQueue() {
  const snapshot = useDashboardStore((s) => s.snapshot)
  const suggestions = useDashboardStore((s) => s.derived?.suggestions ?? NO_DISPATCHES)
  const dismissed = useDashboardStore((s) => s.dismissedSuggestionIds)
  const selectedSiteId = useDashboardStore((s) => s.selectedSiteId)
  const { approve, cancel, dismiss, selectSite } = useDashboardStore.getState()
  const [busyId, setBusyId] = useState<string | null>(null)

  const nameOf = (id: string) => snapshot?.locations.find((l) => l.id === id)?.name ?? id
  const all: Dispatch[] = [
    ...suggestions.filter((s) => !dismissed.includes(s.dispatch_id)),
    ...(snapshot?.dispatches ?? []).slice().sort((a, b) => b.updated_at.localeCompare(a.updated_at)),
  ]

  const run = async (id: string, action: () => Promise<void>) => {
    setBusyId(id)
    try {
      await action()
    } finally {
      setBusyId(null)
    }
  }

  return (
    <Panel title="Dispatch Queue">
      <div className="space-y-3 p-2">
        {all.length === 0 && <p className="text-sm text-slate-400">No dispatches.</p>}
        {GROUPS.map(({ status, label }) => {
          const items = all.filter((d) => d.status === status)
          if (items.length === 0) return null
          return (
            <section key={status}>
              <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500 dark:text-slate-400">
                {label} ({items.length})
              </h3>
              <ul className="space-y-1">
                {items.map((d) => (
                  <li
                    key={d.dispatch_id}
                    onClick={() => selectSite(d.to_site)}
                    className={`cursor-pointer rounded border px-2 py-1.5 text-xs ${STATUS_CLASS[d.status]} ${
                      d.to_site === selectedSiteId ? 'ring-2 ring-sky-400' : ''
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">
                        {nameOf(d.from_site)} → {nameOf(d.to_site)}
                      </span>
                      {d.eta_minutes !== undefined && d.status !== 'delivered' && d.status !== 'cancelled' && (
                        <span className="whitespace-nowrap text-slate-500 dark:text-slate-400">ETA {d.eta_minutes} min</span>
                      )}
                    </div>
                    <div className="mt-0.5 flex items-center justify-between gap-2">
                      <span>{formatItems(d.items)}</span>
                      <span className="flex shrink-0 gap-1" onClick={(e) => e.stopPropagation()}>
                        {busyId === d.dispatch_id && <span className="text-slate-400">Working...</span>}
                        {busyId !== d.dispatch_id && d.status === 'suggested' && (
                          <>
                            <Button variant="primary" onClick={() => run(d.dispatch_id, () => approve(d))}>
                              Approve
                            </Button>
                            <Button variant="plain" onClick={() => dismiss(d.dispatch_id)}>
                              Dismiss
                            </Button>
                          </>
                        )}
                        {busyId !== d.dispatch_id && d.status === 'pending' && (
                          <Button variant="plain" onClick={() => run(d.dispatch_id, () => cancel(d.dispatch_id))}>
                            Cancel
                          </Button>
                        )}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )
        })}
      </div>
    </Panel>
  )
}

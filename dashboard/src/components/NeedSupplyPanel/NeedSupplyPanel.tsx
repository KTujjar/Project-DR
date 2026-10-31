import { useState } from 'react'
import { SEVERITY_RANK } from '../../logic/severity'
import type { SiteRow } from '../../logic/sites'
import { useDashboardStore } from '../../store/useDashboardStore'
import { ITEM_TYPES } from '../../types/schemas'
import { ITEM_LABEL } from '../labels'
import { Panel } from '../Panel'
import { SeverityBadge } from '../SeverityBadge'

const NO_ROWS: SiteRow[] = []
const TREND_ARROW = { up: '▲', down: '▼', flat: '–' }
const TREND_CLASS = { up: 'text-red-600', down: 'text-green-600', flat: 'text-slate-400' }

type SortKey = 'severity' | 'name'

function sortRows(rows: SiteRow[], key: SortKey) {
  return [...rows].sort((a, b) =>
    key === 'name'
      ? a.location.name.localeCompare(b.location.name)
      : SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || b.headcount - a.headcount,
  )
}

export function NeedSupplyPanel() {
  const rows = useDashboardStore((s) => s.derived?.rows ?? NO_ROWS)
  const selectedSiteId = useDashboardStore((s) => s.selectedSiteId)
  const selectSite = useDashboardStore((s) => s.selectSite)
  const [sortKey, setSortKey] = useState<SortKey>('severity')

  const sortControl = (
    <select
      value={sortKey}
      onChange={(e) => setSortKey(e.target.value as SortKey)}
      className="rounded border border-slate-300 px-1 py-0.5 text-xs"
      aria-label="Sort shelters"
    >
      <option value="severity">Sort: severity</option>
      <option value="name">Sort: name</option>
    </select>
  )

  return (
    <Panel title="Need vs Supply (24h)" actions={sortControl}>
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-slate-50 text-left text-slate-500">
          <tr>
            <th className="px-2 py-1 font-medium">Shelter</th>
            <th className="px-1 py-1 font-medium">People</th>
            {ITEM_TYPES.map((item) => (
              <th key={item} className="px-1 py-1 text-right font-medium">
                {ITEM_LABEL[item]}
              </th>
            ))}
            <th className="px-2 py-1 font-medium" />
          </tr>
        </thead>
        <tbody>
          {sortRows(rows, sortKey).map((row) => {
            const id = row.location.id
            return (
              <tr
                key={id}
                onClick={() => selectSite(id)}
                className={`cursor-pointer border-t border-slate-100 hover:bg-slate-50 ${
                  id === selectedSiteId ? 'bg-sky-50 outline outline-2 -outline-offset-2 outline-sky-400' : ''
                }`}
              >
                <td className="px-2 py-1.5 font-medium">{row.location.name}</td>
                <td className="whitespace-nowrap px-1 py-1.5">
                  {row.headcount} <span className={TREND_CLASS[row.trend]}>{TREND_ARROW[row.trend]}</span>
                  {row.capacityRatio !== null && (
                    <div className={row.overCapacity ? 'font-semibold text-red-600' : 'text-slate-400'}>
                      {Math.round(row.capacityRatio * 100)}% cap
                    </div>
                  )}
                </td>
                {ITEM_TYPES.map((item) => {
                  const s = row.items[item]
                  return (
                    <td key={item} className="whitespace-nowrap px-1 py-1.5 text-right tabular-nums">
                      <div title={`On hand ${s.onHand} / need ${s.need}`}>
                        {s.onHand.toLocaleString()}
                        <span className="text-slate-400">/{s.need.toLocaleString()}</span>
                      </div>
                      {s.shortfall > 0 && <div className="font-semibold text-red-600">-{s.shortfall.toLocaleString()}</div>}
                    </td>
                  )
                })}
                <td className="px-2 py-1.5">
                  <SeverityBadge severity={row.severity} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </Panel>
  )
}
